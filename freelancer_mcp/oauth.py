"""Single-user OAuth 2.1 authorization server for the MCP endpoint.

Claude registers itself with Dynamic Client Registration, then sends you to /login.
You sign in with a password plus a 6-digit code from an authenticator app, and Claude
receives short-lived access tokens bound to this MCP server, with rotating refresh
tokens. Everything is stored in its own small SQLite file (tokens only as SHA-256
hashes), separate from the agent's database.

The MCP SDK provides the /authorize, /token, /register and /revoke endpoints and the
discovery metadata; this module implements the storage and the login step behind them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import pyotp
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from freelancer_mcp.config import Settings

log = logging.getLogger(__name__)

SCOPE = "freelancer"
OWNER_SUBJECT = "owner"

# Claude's hosted apps (web, desktop, mobile) use this callback; the claude.com one is
# documented as a possible future value.
CLAUDE_REDIRECT_URIS = {
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
}

PENDING_TTL = 600
CODE_TTL = 300
MAX_CLIENTS = 50
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 900

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    info TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_authorizations (
    request_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    params TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    data TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('access', 'refresh')),
    family_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    resource TEXT,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS tokens_family ON tokens (family_id);
CREATE TABLE IF NOT EXISTS login_guard (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    failures INTEGER NOT NULL,
    window_start REAL NOT NULL,
    locked_until REAL NOT NULL,
    last_totp_counter INTEGER NOT NULL
);
INSERT OR IGNORE INTO login_guard VALUES (1, 0, 0, 0, -1);
"""


# --- Password hashing (stdlib scrypt) ---------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=64 * 1024 * 1024
    )
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"scrypt:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:{b64(salt)}:{b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = encoded.split(":")
        if scheme != "scrypt":
            return False
        unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        expected = unb64(digest_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=unb64(salt_b64), n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def is_loopback_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


# --- Provider ----------------------------------------------------------------


class SingleUserOAuthProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._db_path = Path(settings.auth_db_path)
        self._lock = threading.Lock()
        self._totp = pyotp.TOTP(settings.owner_totp_secret) if settings.owner_totp_secret else None
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self._db_path, timeout=5)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                with conn:
                    yield conn
            finally:
                conn.close()

    # Clients -------------------------------------------------------------

    def _allowed_redirect(self, uri: str) -> bool:
        if uri in CLAUDE_REDIRECT_URIS:
            return True
        return self.settings.allow_loopback_redirects and is_loopback_redirect(uri)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._db() as db:
            row = db.execute("SELECT info FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        bad = [u for u in uris if not self._allowed_redirect(u)]
        if not uris or bad:
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description=f"redirect_uri not allowed on this server: {', '.join(bad) or '(none)'}",
            )
        now = time.time()
        with self._db() as db:
            # Claude registers a fresh client on each new connection, so drop clients that
            # never finished signing in, and clients whose tokens have all expired.
            db.execute(
                """DELETE FROM clients WHERE created_at < ? AND client_id NOT IN
                   (SELECT client_id FROM tokens WHERE expires_at > ?)""",
                (now - PENDING_TTL, now),
            )
            (count,) = db.execute("SELECT COUNT(*) FROM clients").fetchone()
            if count >= MAX_CLIENTS:
                raise RegistrationError(
                    error="invalid_client_metadata",
                    error_description="Too many registered clients; run `python mcp_server.py revoke-tokens`.",
                )
            db.execute(
                "INSERT INTO clients (client_id, info, created_at) VALUES (?, ?, ?)",
                (client_info.client_id, client_info.model_dump_json(), now),
            )
        log.info("Registered OAuth client %s (%s)", client_info.client_id, client_info.client_name)

    # Authorization ------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource is not None and params.resource.rstrip("/") != self.settings.mcp_url:
            raise AuthorizeError(
                error="invalid_target", error_description=f"This server only issues tokens for {self.settings.mcp_url}"
            )
        request_id = secrets.token_urlsafe(32)
        now = time.time()
        with self._db() as db:
            db.execute("DELETE FROM pending_authorizations WHERE created_at < ?", (now - PENDING_TTL,))
            db.execute(
                "INSERT INTO pending_authorizations VALUES (?, ?, ?, ?)",
                (request_id, client.client_id, params.model_dump_json(), now),
            )
        return f"{self.settings.public_url}/login?request={request_id}"

    def _load_pending(self, request_id: str) -> tuple[OAuthClientInformationFull, AuthorizationParams] | None:
        with self._db() as db:
            row = db.execute(
                """SELECT p.params, c.info FROM pending_authorizations p
                   JOIN clients c ON c.client_id = p.client_id
                   WHERE p.request_id = ? AND p.created_at > ?""",
                (request_id, time.time() - PENDING_TTL),
            ).fetchone()
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(row[1]), AuthorizationParams.model_validate_json(row[0])

    def _check_credentials(self, password: str, code: str) -> str | None:
        """Returns None on success, else a message for the login page."""
        now = time.time()
        with self._db() as db:
            failures, window_start, locked_until, last_counter = db.execute(
                "SELECT failures, window_start, locked_until, last_totp_counter FROM login_guard WHERE id = 1"
            ).fetchone()
            if now < locked_until:
                return f"Too many failed attempts. Try again in {int(locked_until - now) // 60 + 1} minutes."
            if now - window_start > LOCKOUT_SECONDS:
                failures, window_start = 0, now

            password_ok = verify_password(password, self.settings.owner_password_hash)
            counter = self._match_totp(code.strip().replace(" ", ""), last_counter)
            if password_ok and counter is not None:
                db.execute(
                    "UPDATE login_guard SET failures = 0, window_start = ?, locked_until = 0, last_totp_counter = ?"
                    " WHERE id = 1",
                    (now, counter),
                )
                return None

            failures += 1
            locked_until = now + LOCKOUT_SECONDS if failures >= MAX_FAILED_LOGINS else 0
            db.execute(
                "UPDATE login_guard SET failures = ?, window_start = ?, locked_until = ? WHERE id = 1",
                (failures, window_start, locked_until),
            )
        log.warning("Failed MCP login attempt (%d in current window)", failures)
        return "Wrong password or code."

    def _match_totp(self, code: str, last_counter: int) -> int | None:
        """Accepts the current code or one step either side, never the same code twice."""
        if self._totp is None or not code.isdigit():
            return None
        current = int(time.time() // self._totp.interval)
        for offset in (0, -1, 1):
            counter = current + offset
            if counter > last_counter and hmac.compare_digest(self._totp.generate_otp(counter), code):
                return counter
        return None

    def _issue_code(self, client: OAuthClientInformationFull, params: AuthorizationParams, request_id: str) -> str:
        code = secrets.token_urlsafe(32)
        data = AuthorizationCode(
            code="",
            scopes=params.scopes or [SCOPE],
            expires_at=time.time() + CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.settings.mcp_url,
            subject=OWNER_SUBJECT,
        )
        with self._db() as db:
            db.execute("DELETE FROM pending_authorizations WHERE request_id = ?", (request_id,))
            db.execute("DELETE FROM auth_codes WHERE expires_at < ?", (time.time(),))
            db.execute(
                "INSERT INTO auth_codes VALUES (?, ?, ?, ?)",
                (_sha256(code), client.client_id, data.model_dump_json(), data.expires_at),
            )
        return code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self._db() as db:
            row = db.execute(
                "SELECT data FROM auth_codes WHERE code_hash = ? AND client_id = ?",
                (_sha256(authorization_code), client.client_id),
            ).fetchone()
        if row is None:
            return None
        return AuthorizationCode.model_validate_json(row[0]).model_copy(update={"code": authorization_code})

    # Tokens ---------------------------------------------------------------

    def _issue_tokens(self, db: sqlite3.Connection, client_id: str, scopes: list[str], family_id: str) -> OAuthToken:
        now = time.time()
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        rows = [
            (_sha256(access), "access", family_id, client_id, " ".join(scopes), self.settings.mcp_url,
             now + self.settings.access_token_ttl),
            (_sha256(refresh), "refresh", family_id, client_id, " ".join(scopes), self.settings.mcp_url,
             now + self.settings.refresh_token_ttl),
        ]  # fmt: skip
        db.execute("DELETE FROM tokens WHERE expires_at < ?", (now,))
        db.executemany(
            "INSERT INTO tokens (token_hash, kind, family_id, client_id, scopes, resource, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        return OAuthToken(
            access_token=access,
            expires_in=self.settings.access_token_ttl,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with self._db() as db:
            deleted = db.execute(
                "DELETE FROM auth_codes WHERE code_hash = ?", (_sha256(authorization_code.code),)
            ).rowcount
            if not deleted:  # already used
                raise TokenError(error="invalid_grant", error_description="authorization code already used")
            return self._issue_tokens(db, client.client_id, authorization_code.scopes, secrets.token_hex(16))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        with self._db() as db:
            row = db.execute(
                "SELECT family_id, client_id, scopes, resource, expires_at, used FROM tokens"
                " WHERE token_hash = ? AND kind = 'refresh'",
                (_sha256(refresh_token),),
            ).fetchone()
            if row is None:
                return None
            family_id, client_id, scopes, resource, expires_at, used = row
            if used:
                # A rotated-out refresh token came back: assume it leaked and end the session.
                db.execute("DELETE FROM tokens WHERE family_id = ?", (family_id,))
                log.warning("Refresh token reuse detected for client %s; revoked its tokens", client_id)
                return None
        return RefreshToken(
            token=refresh_token,
            client_id=client_id,
            scopes=scopes.split(),
            expires_at=int(expires_at),
            resource=resource,
            subject=OWNER_SUBJECT,
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        with self._db() as db:
            row = db.execute(
                "SELECT family_id FROM tokens WHERE token_hash = ? AND kind = 'refresh' AND used = 0",
                (_sha256(refresh_token.token),),
            ).fetchone()
            if row is None:
                raise TokenError(error="invalid_grant", error_description="refresh token is no longer valid")
            (family_id,) = row
            db.execute("UPDATE tokens SET used = 1 WHERE token_hash = ?", (_sha256(refresh_token.token),))
            db.execute("DELETE FROM tokens WHERE family_id = ? AND kind = 'access'", (family_id,))
            return self._issue_tokens(db, client.client_id, scopes, family_id)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._db() as db:
            row = db.execute(
                "SELECT client_id, scopes, resource, expires_at FROM tokens"
                " WHERE token_hash = ? AND kind = 'access' AND expires_at > ?",
                (_sha256(token), time.time()),
            ).fetchone()
        if row is None:
            return None
        client_id, scopes, resource, expires_at = row
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes.split(),
            expires_at=int(expires_at),
            resource=resource,
            subject=OWNER_SUBJECT,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._db() as db:
            row = db.execute("SELECT family_id FROM tokens WHERE token_hash = ?", (_sha256(token.token),)).fetchone()
            if row:
                db.execute("DELETE FROM tokens WHERE family_id = ?", (row[0],))

    def revoke_everything(self) -> None:
        with self._db() as db:
            for table in ("tokens", "auth_codes", "pending_authorizations", "clients"):
                db.execute(f"DELETE FROM {table}")

    # Login page -----------------------------------------------------------

    async def login_page(self, request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("request", "")
            pending = self._load_pending(request_id)
            if pending is None:
                return _page("This sign-in link has expired. Start again from Claude.", status=400)
            return _login_form(request_id, *pending)

        form = await request.form()
        request_id = str(form.get("request", ""))
        pending = self._load_pending(request_id)
        if pending is None:
            return _page("This sign-in link has expired. Start again from Claude.", status=400)
        client, params = pending
        redirect_uri = str(params.redirect_uri)

        if form.get("action") == "deny":
            with self._db() as db:
                db.execute("DELETE FROM pending_authorizations WHERE request_id = ?", (request_id,))
            return RedirectResponse(
                construct_redirect_uri(redirect_uri, error="access_denied", state=params.state), status_code=303
            )

        error = self._check_credentials(str(form.get("password", "")), str(form.get("code", "")))
        if error:
            return _login_form(request_id, client, params, error=error, status=401)

        code = self._issue_code(client, params, request_id)
        log.info("Owner approved MCP access for client %s", client.client_id)
        return RedirectResponse(construct_redirect_uri(redirect_uri, code=code, state=params.state), status_code=303)


_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https: http://localhost:* http://127.0.0.1:*; "
    "frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

_STYLE = """
body{font-family:system-ui,sans-serif;max-width:26rem;margin:3rem auto;padding:0 1rem;color:#1a1a1a;background:#fafafa}
h1{font-size:1.3rem}label{display:block;margin-top:1rem;font-weight:600}
input{width:100%;box-sizing:border-box;padding:.6rem;font-size:1rem;margin-top:.3rem}
.row{display:flex;gap:.5rem;margin-top:1.5rem}button{flex:1;padding:.7rem;font-size:1rem}
.who{background:#fff;border:1px solid #ddd;padding:.8rem;border-radius:6px}.err{color:#b00020}
.warn{color:#8a5a00}
"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>Freelancer MCP</title><style>{_STYLE}</style><p>{html.escape(body)}</p>",
        status_code=status,
        headers=_HEADERS,
    )


def _login_form(
    request_id: str,
    client: OAuthClientInformationFull,
    params: AuthorizationParams,
    error: str | None = None,
    status: int = 200,
) -> HTMLResponse:
    redirect_host = urlparse(str(params.redirect_uri)).netloc
    # Anyone can add this server to their own Claude account and send you the resulting
    # sign-in link; approving it would hand their account access to yours.
    warn = (
        "<p class=warn>Only continue if you just clicked Connect in Claude yourself. "
        "If someone sent you this link, close the page.</p>"
    )
    if is_loopback_redirect(str(params.redirect_uri)):
        warn += (
            "<p class=warn>This app runs on a local computer, not on claude.ai. "
            "Only approve it if you just started it yourself.</p>"
        )
    err = f"<p class=err>{html.escape(error)}</p>" if error else ""
    body = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Sign in: Freelancer MCP</title><style>{_STYLE}</style>
<h1>Allow access to your Freelancer.com account?</h1>
<div class=who><b>{html.escape(client.client_name or "Unnamed app")}</b> will be able to search projects,
read messages, and place bids and send messages as you.<br>It returns to <b>{html.escape(redirect_host)}</b>.</div>
{warn}{err}
<form method=post action="/login">
<input type=hidden name=request value="{html.escape(request_id)}">
<label>Password<input type=password name=password autocomplete=current-password required></label>
<label>Authenticator code<input name=code inputmode=numeric autocomplete=one-time-code pattern="[0-9 ]*" required></label>
<div class=row><button name=action value=approve>Allow</button>
<button name=action value=deny formnovalidate>Deny</button></div>
</form>"""
    return HTMLResponse(body, status_code=status, headers=_HEADERS)
