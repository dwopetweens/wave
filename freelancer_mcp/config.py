"""MCP server settings, read from the environment (and `.env` when present).

Secrets (password hash, TOTP secret, the agent's Freelancer token) only ever come
from the environment. Nothing here has a secret default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; systemd passes EnvironmentFile instead
    load_dotenv = None

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ConfigError(RuntimeError):
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    # Public base URL Claude reaches, e.g. https://mcp.example.com (no trailing slash).
    public_url: str
    host: str
    port: int

    # "agent" wires the tools to the existing bidding agent; "fake" serves sample data.
    backend: str
    # The agent's config.yaml, relative to the agent directory the server runs from.
    agent_config: str
    # When true, place_bid and send_message run every check but submit nothing.
    dry_run: bool
    # Optional hard ceiling on a single bid amount, whatever Claude passes.
    max_bid_amount: float | None

    # Client-side throttle in front of the Freelancer API, shared by all tools.
    api_max_calls: int
    api_period_seconds: float

    # OAuth (single user).
    auth_disabled: bool
    auth_db_path: Path
    owner_password_hash: str
    owner_totp_secret: str
    allow_loopback_redirects: bool
    access_token_ttl: int
    refresh_token_ttl: int

    @property
    def mcp_url(self) -> str:
        return f"{self.public_url}/mcp"

    @property
    def public_host(self) -> str:
        return urlparse(self.public_url).netloc


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    if load_dotenv is not None and env_file is not None and Path(env_file).exists():
        load_dotenv(env_file, override=False)

    host = os.environ.get("MCP_HOST", "127.0.0.1").strip()
    port = _int("MCP_PORT", 8765)
    public_url = os.environ.get("MCP_PUBLIC_URL", f"http://127.0.0.1:{port}").strip().rstrip("/")
    parsed = urlparse(public_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ConfigError(f"MCP_PUBLIC_URL must be a bare origin like https://mcp.example.com, got {public_url!r}")
    public_is_loopback = parsed.hostname in LOOPBACK_HOSTS
    if parsed.scheme == "http" and not public_is_loopback:
        raise ConfigError("MCP_PUBLIC_URL must use https unless it points at localhost")

    backend = os.environ.get("MCP_BACKEND", "agent").strip().lower()
    if backend not in {"agent", "fake"}:
        raise ConfigError(f"MCP_BACKEND must be 'agent' or 'fake', got {backend!r}")

    auth_disabled = _bool("MCP_AUTH_DISABLED", False)
    # Behind Nginx the server also listens on 127.0.0.1, so a loopback bind alone does not
    # prove the server is private. Only allow no-auth when the public URL is loopback too.
    if auth_disabled and not (host in LOOPBACK_HOSTS and public_is_loopback):
        raise ConfigError(
            "MCP_AUTH_DISABLED is only allowed for local testing: MCP_HOST and MCP_PUBLIC_URL must both be localhost"
        )

    password_hash = os.environ.get("MCP_OWNER_PASSWORD_HASH", "").strip()
    totp_secret = os.environ.get("MCP_OWNER_TOTP_SECRET", "").strip()
    if not auth_disabled and (not password_hash or not totp_secret):
        raise ConfigError(
            "MCP_OWNER_PASSWORD_HASH and MCP_OWNER_TOTP_SECRET are required. "
            "Run `python mcp_server.py init-auth` to generate them."
        )

    period = _float("MCP_API_PERIOD_SECONDS", 60.0)
    assert period is not None

    return Settings(
        public_url=public_url,
        host=host,
        port=port,
        backend=backend,
        agent_config=os.environ.get("MCP_AGENT_CONFIG", "config.yaml"),
        dry_run=_bool("MCP_DRY_RUN", True),
        max_bid_amount=_float("MCP_MAX_BID_AMOUNT", None),
        api_max_calls=_int("MCP_API_MAX_CALLS", 30),
        api_period_seconds=period,
        auth_disabled=auth_disabled,
        auth_db_path=Path(os.environ.get("MCP_AUTH_DB", "mcp_auth.db")),
        owner_password_hash=password_hash,
        owner_totp_secret=totp_secret,
        allow_loopback_redirects=_bool("MCP_ALLOW_LOOPBACK_REDIRECTS", False),
        access_token_ttl=_int("MCP_ACCESS_TOKEN_TTL", 3600),
        refresh_token_ttl=_int("MCP_REFRESH_TOKEN_TTL", 30 * 24 * 3600),
    )
