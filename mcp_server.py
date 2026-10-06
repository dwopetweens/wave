"""Remote MCP server for the Freelancer.com bidding agent.

    python mcp_server.py               serve over Streamable HTTP (MCP_HOST:MCP_PORT, path /mcp)
    python mcp_server.py init-auth     generate the owner password hash and TOTP secret for .env
    python mcp_server.py revoke-tokens sign every Claude client out

Configuration comes from the environment or `.env`; see `mcp.env.example`.
"""

from __future__ import annotations

import argparse
import functools
import getpass
import logging
import sys
from collections.abc import Callable
from typing import Annotated, Any

import anyio
import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from freelancer_mcp.backend import Backend, BackendError, BidStatus, FakeBackend
from freelancer_mcp.config import ConfigError, Settings, load_settings
from freelancer_mcp.oauth import SCOPE, SingleUserOAuthProvider, hash_password
from freelancer_mcp.ratelimit import RateLimiter

log = logging.getLogger("freelancer_mcp")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
# Writes to Freelancer.com as the owner. Not read-only and not idempotent, so Claude asks
# before each call. Not destructive: bids and messages only add, never delete.
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

INSTRUCTIONS = """\
Manage the owner's Freelancer.com bidding: find projects, research clients, place bids, and handle messages.
An auto-bidding agent works the same account around the clock; this server shares its database.

- search_projects already hides projects the owner or the agent has bid on.
- Before place_bid: call get_project, keep to its bid_rules (amount range, period, currency), write the
  proposal in the chat, show the owner the exact amount, delivery period and text, and only call place_bid
  after they approve it. The server submits the text as given and never rewrites it.
- Write proposals the way the agent does: exactly three paragraphs separated by blank lines (a short
  greeting; one or two sentences starting "I'll" or "I can" naming concrete deliverables from the post; one
  short warm closing statement), 50 to 100 words in total, first person, plain text. Never: dashes used as
  punctuation, questions, a price, a signature, or offers of calls or meetings.
- Errors start with a code. `already_bid`: someone (often the agent) bid already; do not retry.
  `agent_busy`: the agent is processing that project; check again later. `invalid_input`: the message says
  what is allowed; ask the owner before changing any number. `rate_limited`: tell the owner how long to wait.
  `freelancer_auth`: the owner must renew the Freelancer token.
"""


def load_backend(settings: Settings) -> Backend:
    if settings.backend == "fake":
        return FakeBackend()
    try:
        # Imports the agent's own modules (src/, portal.py), so the server must run from its directory.
        from freelancer_mcp.agent_backend import AgentBackend
    except ModuleNotFoundError as exc:
        raise ConfigError(
            f"MCP_BACKEND=agent needs the bidding agent's code next to mcp_server.py (missing: {exc.name})"
        ) from exc
    limiter = RateLimiter(settings.api_max_calls, settings.api_period_seconds)
    return AgentBackend(settings.agent_config, limiter=limiter)


def build_server(settings: Settings, backend: Backend) -> MCPServer:
    async def call(fn: Callable[..., Any], **kwargs: Any) -> Any:
        try:
            return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs))
        except BackendError as exc:
            raise ToolError(f"{exc.code}: {exc.message}") from exc
        except Exception as exc:
            log.exception("Unexpected error in %s", getattr(fn, "__name__", fn))
            raise ToolError(
                f"internal_error: {type(exc).__name__}. The server logged the details (journalctl -u freelancer-mcp)."
            ) from exc

    provider = None
    auth = None
    if not settings.auth_disabled:
        provider = SingleUserOAuthProvider(settings)
        auth = AuthSettings(
            issuer_url=settings.public_url,
            resource_server_url=settings.mcp_url,
            validate_token_resource=True,
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
            ),
            revocation_options=RevocationOptions(enabled=True),
        )

    mode = "DRY RUN: place_bid and send_message check everything but submit nothing." if settings.dry_run else ""
    server = MCPServer(
        name="freelancer",
        title="Freelancer.com",
        instructions=f"{INSTRUCTIONS}\n{mode}".strip(),
        auth_server_provider=provider,
        auth=auth,
    )

    if provider is not None:
        server.custom_route("/login", methods=["GET", "POST"], include_in_schema=False)(provider.login_page)

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "backend": settings.backend, "dry_run": settings.dry_run})

    @server.tool(title="Search projects", annotations=READ_ONLY)
    async def search_projects(
        query: Annotated[str, Field(description="Keywords, e.g. 'telegram bot'. Empty for all.")] = "",
        min_budget: Annotated[
            float | None, Field(ge=0, description="Lowest budget, in each project's currency.")
        ] = None,
        max_budget: Annotated[
            float | None, Field(ge=0, description="Highest budget, in each project's currency.")
        ] = None,
        skills: Annotated[
            list[str] | None,
            Field(
                description="Skill names, e.g. ['wordpress', 'dns']; a project matches if any overlap. "
                "With no query, each skill (up to 5) is searched."
            ),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> list[dict[str, Any]]:
        """Search active Freelancer.com projects. Projects already bid on are left out.

        Each result says whether the auto-agent has seen it (agent.status, agent.score)."""
        if min_budget is not None and max_budget is not None and min_budget > max_budget:
            raise ToolError("invalid_input: min_budget is greater than max_budget")
        return await call(
            backend.search_projects,
            query=query.strip(),
            min_budget=min_budget,
            max_budget=max_budget,
            skills=[s.strip() for s in skills or [] if s.strip()],
            limit=limit,
        )

    @server.tool(title="Get project", annotations=READ_ONLY)
    async def get_project(project_id: Annotated[int, Field(gt=0)]) -> dict[str, Any]:
        """Full project details: description, the client's country, rating, reviews and payment
        verification, the number of bids so far, the agent's score or draft if any, and bid_rules
        (the amount range and delivery period place_bid will accept)."""
        return await call(backend.get_project, project_id=project_id)

    @server.tool(title="Place bid", annotations=WRITE)
    async def place_bid(
        project_id: Annotated[int, Field(gt=0)],
        amount: Annotated[
            float, Field(gt=0, description="In the project's currency; for hourly projects, the hourly rate.")
        ],
        period_days: Annotated[int, Field(ge=1, le=365, description="Delivery time in days; see bid_rules.")],
        description: Annotated[str, Field(min_length=1, description="The proposal text, submitted as given.")],
    ) -> dict[str, Any]:
        """Submit a bid as the owner and record it in the agent's database. The milestone is always 100%.

        Only call this after the owner has approved the exact amount, period and text. The result
        lists style_warnings where the text departs from the owner's proposal rules."""
        if not description.strip():
            raise ToolError("invalid_input: description is empty")
        if settings.max_bid_amount is not None and amount > settings.max_bid_amount:
            raise ToolError(
                f"invalid_input: {amount} is above this server's MCP_MAX_BID_AMOUNT of {settings.max_bid_amount}"
            )
        return await call(
            backend.place_bid,
            project_id=project_id,
            amount=amount,
            period_days=period_days,
            description=description,
            dry_run=settings.dry_run,
        )

    @server.tool(title="List my bids", annotations=READ_ONLY)
    async def list_my_bids(status: BidStatus = "active") -> list[dict[str, Any]]:
        """The owner's bids, newest first: active, awarded, rejected, or all."""
        return await call(backend.list_my_bids, status=status)

    @server.tool(title="Get messages", annotations=READ_ONLY)
    async def get_messages(
        thread_id: Annotated[int | None, Field(gt=0)] = None,
        project_id: Annotated[int | None, Field(gt=0)] = None,
    ) -> dict[str, Any]:
        """Messages in a thread, looked up by thread_id or by project_id (give exactly one)."""
        if (thread_id is None) == (project_id is None):
            raise ToolError("invalid_input: give exactly one of thread_id or project_id")
        return await call(backend.get_messages, thread_id=thread_id, project_id=project_id)

    @server.tool(title="Send message", annotations=WRITE)
    async def send_message(
        thread_id: Annotated[int, Field(gt=0)],
        text: Annotated[str, Field(min_length=1)],
    ) -> dict[str, Any]:
        """Send a message as the owner. Only call this after the owner has approved the text."""
        if not text.strip():
            raise ToolError("invalid_input: text is empty")
        return await call(backend.send_message, thread_id=thread_id, text=text, dry_run=settings.dry_run)

    return server


def build_app(settings: Settings, backend: Backend) -> Starlette:
    server = build_server(settings, backend)
    origin = settings.public_url
    # Nginx's $host drops the port, so accept the public host with and without it.
    public_hosts = sorted({settings.public_host, settings.public_host.rsplit(":", 1)[0]})
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*public_hosts, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[origin, "https://claude.ai", "https://claude.com", "http://127.0.0.1:*", "http://localhost:*"],
    )
    # Stateless: each request stands alone, so restarts never strand a Claude session.
    return server.streamable_http_app(stateless_http=True, transport_security=security, host=settings.host)


def cmd_init_auth() -> int:
    import pyotp

    password = getpass.getpass("New MCP login password (12+ characters): ")
    if len(password) < 12:
        print("Too short.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat it: ") != password:
        print("Passwords differ.", file=sys.stderr)
        return 1
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name="owner", issuer_name="Freelancer MCP")
    print("\nAdd these two lines to .env (never commit it):\n")
    print(f"MCP_OWNER_PASSWORD_HASH={hash_password(password)}")
    print(f"MCP_OWNER_TOTP_SECRET={secret}")
    print("\nIn your authenticator app, add an account with this setup key:", secret)
    print("or open this link on the phone:", uri)
    return 0


def cmd_revoke_tokens(settings: Settings) -> int:
    SingleUserOAuthProvider(settings).revoke_everything()
    print("All MCP clients and tokens revoked. Claude will ask you to sign in again.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "init-auth", "revoke-tokens"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "init-auth":
        return cmd_init_auth()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.command == "revoke-tokens":
        return cmd_revoke_tokens(settings)

    try:
        backend = load_backend(settings)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    app = build_app(settings, backend)
    log.info(
        "Serving %s (backend=%s, dry_run=%s, auth=%s)",
        settings.mcp_url,
        settings.backend,
        settings.dry_run,
        "off" if settings.auth_disabled else "oauth",
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
