"""End-to-end tests: a real uvicorn server, Claude's OAuth flow, and every tool.

Runs against FakeBackend, so nothing reaches Freelancer.com.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx2
import pyotp
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from freelancer_mcp.backend import FakeBackend
from freelancer_mcp.config import Settings
from freelancer_mcp.oauth import hash_password
from mcp_server import build_app

CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "correct horse battery staple"
TOTP_SECRET = pyotp.random_base32()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_settings(tmp_path: Path, **overrides) -> Settings:
    port = _free_port()
    settings = Settings(
        public_url=f"http://127.0.0.1:{port}",
        host="127.0.0.1",
        port=port,
        backend="fake",
        dry_run=True,
        max_bid_amount=None,
        api_max_calls=1000,
        api_period_seconds=60,
        auth_disabled=False,
        auth_db_path=tmp_path / "auth.db",
        owner_password_hash=hash_password(PASSWORD),
        owner_totp_secret=TOTP_SECRET,
        allow_loopback_redirects=False,
        access_token_ttl=3600,
        refresh_token_ttl=86400,
    )
    return replace(settings, **overrides)


class LiveServer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.url = settings.public_url
        config = uvicorn.Config(
            build_app(settings, FakeBackend()), host="127.0.0.1", port=settings.port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self):
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture
def live(tmp_path):
    with LiveServer(make_settings(tmp_path)) as server:
        yield server


def _mcp_url(http: httpx2.Client) -> str:
    return f"{str(http.base_url).rstrip('/')}/mcp"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register(http: httpx2.Client, redirect_uri: str = CLAUDE_CALLBACK) -> httpx2.Response:
    return http.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


def _start_authorize(http: httpx2.Client, client_id: str, challenge: str, **extra) -> httpx2.Response:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "scope": "freelancer",
        "resource": _mcp_url(http),
    }
    params.update(extra)
    return http.get("/authorize", params=params)


def _current_code(offset_steps: int = 0) -> str:
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.generate_otp(int(time.time() // totp.interval) + offset_steps)


def sign_in(http: httpx2.Client) -> tuple[str, dict]:
    """Runs the whole flow Claude runs. Returns (client_id, token response)."""
    client_id = _register(http).json()["client_id"]
    verifier, challenge = _pkce()
    resp = _start_authorize(http, client_id, challenge)
    assert resp.status_code == 302, resp.text
    login_url = urlparse(resp.headers["location"])
    request_id = parse_qs(login_url.query)["request"][0]

    assert http.get(f"/login?request={request_id}").status_code == 200
    resp = http.post(
        "/login", data={"request": request_id, "password": PASSWORD, "code": _current_code(), "action": "approve"}
    )
    assert resp.status_code == 303, resp.text
    callback = urlparse(resp.headers["location"])
    assert f"{callback.scheme}://{callback.netloc}{callback.path}" == CLAUDE_CALLBACK
    query = parse_qs(callback.query)
    assert query["state"] == ["xyz"]

    resp = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": CLAUDE_CALLBACK,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": _mcp_url(http),
        },
    )
    assert resp.status_code == 200, resp.text
    return client_id, resp.json() | {"_code": query["code"][0], "_verifier": verifier}


@asynccontextmanager
async def mcp_session(url: str, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(f"{url}/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session


def _result(result) -> object:
    assert not result.is_error, result.content[0].text
    return result.structured_content["result"] if "result" in result.structured_content else result.structured_content


# --- Discovery ----------------------------------------------------------------


def test_unauthenticated_mcp_gets_401_with_resource_metadata(live):
    with httpx2.Client(base_url=live.url) as http:
        resp = http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401
        assert "resource_metadata=" in resp.headers["www-authenticate"]

        prm = http.get("/.well-known/oauth-protected-resource/mcp").json()
        assert prm["resource"] == f"{live.url}/mcp"
        assert prm["authorization_servers"][0].rstrip("/") == live.url

        asm = http.get("/.well-known/oauth-authorization-server").json()
        assert asm["registration_endpoint"].endswith("/register")
        assert asm["code_challenge_methods_supported"] == ["S256"]


def test_healthz_is_public(live):
    with httpx2.Client(base_url=live.url) as http:
        assert http.get("/healthz").json() == {"ok": True, "backend": "fake", "dry_run": True}


# --- Registration and sign-in -----------------------------------------------------


def test_registration_rejects_foreign_redirects(live):
    with httpx2.Client(base_url=live.url) as http:
        resp = _register(http, "https://evil.example/callback")
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_redirect_uri"
        assert _register(http, "http://localhost:6274/oauth/callback").status_code == 400


def test_loopback_redirects_allowed_when_enabled(tmp_path):
    with LiveServer(make_settings(tmp_path, allow_loopback_redirects=True)) as server:
        with httpx2.Client(base_url=server.url) as http:
            assert _register(http, "http://localhost:6274/oauth/callback").status_code == 201


def test_full_oauth_flow_and_tools(live):
    with httpx2.Client(base_url=live.url) as http:
        _, tokens = sign_in(http)
        assert tokens["token_type"] == "Bearer"
        assert tokens["refresh_token"]

    async def run():
        async with mcp_session(live.url, tokens["access_token"]) as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}
            assert set(tools) == {
                "search_projects", "get_project", "place_bid", "list_my_bids", "get_messages", "send_message",
            }  # fmt: skip
            for name in ("place_bid", "send_message"):
                assert tools[name].annotations.read_only_hint is False
                assert tools[name].annotations.idempotent_hint is False
            for name in ("search_projects", "get_project", "list_my_bids", "get_messages"):
                assert tools[name].annotations.read_only_hint is True

            projects = _result(await session.call_tool("search_projects", {"skills": ["python"]}))
            ids = [p["id"] for p in projects]
            assert 40000003 not in ids, "projects already bid on must be hidden"
            assert 40000001 in ids

            project = _result(await session.call_tool("get_project", {"project_id": 40000001}))
            assert {"country", "rating", "payment_verified", "hire_rate"} <= set(project["client"])
            assert project["bid_count"] == 14

            bids = _result(await session.call_tool("list_my_bids", {"status": "active"}))
            assert [b["project_id"] for b in bids] == [40000003]

            thread = _result(await session.call_tool("get_messages", {"project_id": 40000003}))
            assert thread["thread_id"] == 80000001

    import anyio

    anyio.run(run)


def test_wrong_password_or_code_is_refused(live):
    with httpx2.Client(base_url=live.url) as http:
        client_id = _register(http).json()["client_id"]
        _, challenge = _pkce()
        location = _start_authorize(http, client_id, challenge).headers["location"]
        request_id = parse_qs(urlparse(location).query)["request"][0]

        bad_password = {"request": request_id, "password": "nope", "code": _current_code(), "action": "approve"}
        assert http.post("/login", data=bad_password).status_code == 401
        bad_code = {"request": request_id, "password": PASSWORD, "code": "000000", "action": "approve"}
        assert http.post("/login", data=bad_code).status_code == 401


def test_totp_code_cannot_be_replayed(live):
    with httpx2.Client(base_url=live.url) as http:
        sign_in(http)
        client_id = _register(http).json()["client_id"]
        _, challenge = _pkce()
        location = _start_authorize(http, client_id, challenge).headers["location"]
        request_id = parse_qs(urlparse(location).query)["request"][0]
        # The code used in sign_in (and anything earlier) is spent.
        for step in (-1, 0):
            resp = http.post(
                "/login",
                data={"request": request_id, "password": PASSWORD, "code": _current_code(step), "action": "approve"},
            )
            assert resp.status_code == 401


def test_lockout_after_repeated_failures(live):
    with httpx2.Client(base_url=live.url) as http:
        client_id = _register(http).json()["client_id"]
        _, challenge = _pkce()
        location = _start_authorize(http, client_id, challenge).headers["location"]
        request_id = parse_qs(urlparse(location).query)["request"][0]
        for _ in range(5):
            http.post("/login", data={"request": request_id, "password": "x", "code": "1", "action": "approve"})
        resp = http.post(
            "/login", data={"request": request_id, "password": PASSWORD, "code": _current_code(), "action": "approve"}
        )
        assert resp.status_code == 401
        assert "Too many failed attempts" in resp.text


def test_deny_returns_access_denied(live):
    with httpx2.Client(base_url=live.url) as http:
        client_id = _register(http).json()["client_id"]
        _, challenge = _pkce()
        location = _start_authorize(http, client_id, challenge).headers["location"]
        request_id = parse_qs(urlparse(location).query)["request"][0]
        resp = http.post("/login", data={"request": request_id, "action": "deny"})
        assert resp.status_code == 303
        assert parse_qs(urlparse(resp.headers["location"]).query)["error"] == ["access_denied"]


def test_authorize_rejects_other_resource(live):
    with httpx2.Client(base_url=live.url) as http:
        client_id = _register(http).json()["client_id"]
        _, challenge = _pkce()
        resp = _start_authorize(http, client_id, challenge, resource="https://other.example/mcp")
        assert resp.status_code in (302, 400)
        if resp.status_code == 302:
            assert parse_qs(urlparse(resp.headers["location"]).query)["error"] == ["invalid_target"]


# --- Tokens ---------------------------------------------------------------------


def test_code_is_single_use_and_refresh_rotates(live):
    with httpx2.Client(base_url=live.url) as http:
        client_id, tokens = sign_in(http)

        reuse = http.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": tokens["_code"],
                "redirect_uri": CLAUDE_CALLBACK,
                "client_id": client_id,
                "code_verifier": tokens["_verifier"],
            },
        )
        assert reuse.status_code == 400
        assert reuse.json()["error"] == "invalid_grant"

        refresh = lambda token: http.post(
            "/token", data={"grant_type": "refresh_token", "refresh_token": token, "client_id": client_id}
        )
        rotated = refresh(tokens["refresh_token"])
        assert rotated.status_code == 200, rotated.text
        new = rotated.json()
        assert new["refresh_token"] != tokens["refresh_token"]

        # The old access token died with the rotation; the new one works.
        assert _authorized(live.url, tokens["access_token"]) is False
        assert _authorized(live.url, new["access_token"]) is True

        # Replaying the rotated-out refresh token revokes the whole session.
        replay = refresh(tokens["refresh_token"])
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"
        assert _authorized(live.url, new["access_token"]) is False


def _authorized(url: str, token: str) -> bool:
    resp = httpx2.post(
        f"{url}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"},
    )
    return resp.status_code != 401


def test_tokens_are_stored_hashed(live, tmp_path):
    with httpx2.Client(base_url=live.url) as http:
        _, tokens = sign_in(http)
    raw = (tmp_path / "auth.db").read_bytes()
    for name in ("auth.db-wal",):
        wal = tmp_path / name
        if wal.exists():
            raw += wal.read_bytes()
    assert tokens["access_token"].encode() not in raw
    assert tokens["refresh_token"].encode() not in raw


# --- Write tools ---------------------------------------------------------------


def test_dry_run_submits_nothing(live):
    with httpx2.Client(base_url=live.url) as http:
        _, tokens = sign_in(http)

    async def run():
        async with mcp_session(live.url, tokens["access_token"]) as session:
            args = {"project_id": 40000001, "amount": 400, "period_days": 7, "description": "Proposal text"}
            result = _result(await session.call_tool("place_bid", args))
            assert result["dry_run"] is True and result["submitted"] is False
            # Still biddable: nothing was recorded.
            projects = _result(await session.call_tool("search_projects", {}))
            assert 40000001 in [p["id"] for p in projects]

            sent = _result(await session.call_tool("send_message", {"thread_id": 80000001, "text": "Hi"}))
            assert sent["sent"] is False

    import anyio

    anyio.run(run)


def test_live_bid_is_recorded_and_never_doubled(tmp_path):
    with LiveServer(make_settings(tmp_path, dry_run=False, max_bid_amount=1000)) as server:
        with httpx2.Client(base_url=server.url) as http:
            _, tokens = sign_in(http)

        async def run():
            async with mcp_session(server.url, tokens["access_token"]) as session:
                args = {"project_id": 40000001, "amount": 400, "period_days": 7, "description": "Proposal text"}
                result = _result(await session.call_tool("place_bid", args))
                assert result["submitted"] is True

                again = await session.call_tool("place_bid", args)
                assert again.is_error and "already_bid" in again.content[0].text

                projects = _result(await session.call_tool("search_projects", {}))
                assert 40000001 not in [p["id"] for p in projects]

                too_big = await session.call_tool("place_bid", {**args, "project_id": 40000002, "amount": 5000})
                assert too_big.is_error and "MCP_MAX_BID_AMOUNT" in too_big.content[0].text

        import anyio

        anyio.run(run)


def test_tool_errors_are_actionable(live):
    with httpx2.Client(base_url=live.url) as http:
        _, tokens = sign_in(http)

    async def run():
        async with mcp_session(live.url, tokens["access_token"]) as session:
            missing = await session.call_tool("get_project", {"project_id": 123})
            assert missing.is_error and "not_found" in missing.content[0].text
            both = await session.call_tool("get_messages", {"thread_id": 1, "project_id": 2})
            assert both.is_error and "exactly one" in both.content[0].text
            bad = await session.call_tool(
                "place_bid", {"project_id": 40000001, "amount": -5, "period_days": 7, "description": "x"}
            )
            assert bad.is_error

    import anyio

    anyio.run(run)


def test_settings_refuse_unauthenticated_public_server(monkeypatch):
    from freelancer_mcp.config import ConfigError, load_settings

    monkeypatch.setenv("MCP_AUTH_DISABLED", "1")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com")
    with pytest.raises(ConfigError):
        load_settings(env_file=None)
    monkeypatch.setenv("MCP_PUBLIC_URL", "http://mcp.example.com")
    monkeypatch.setenv("MCP_AUTH_DISABLED", "0")
    with pytest.raises(ConfigError):
        load_settings(env_file=None)
