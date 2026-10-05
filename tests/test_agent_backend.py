"""AgentBackend against the real bidding-agent code and a fake Freelancer API.

Needs the agent's code: set AGENT_DIR to its directory (the one holding src/ and
portal.py), with its requirements installed. Skipped otherwise.

The agent's own FreelancerClient makes real HTTP calls (retries, headers, JSON
bodies and parsing included) to a local fake of the Freelancer endpoints it uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

AGENT_DIR = os.environ.get("AGENT_DIR")
if not AGENT_DIR or not (Path(AGENT_DIR) / "src" / "storage.py").exists():
    pytest.skip("set AGENT_DIR to the bidding agent's directory", allow_module_level=True)
sys.path.insert(0, AGENT_DIR)

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from freelancer_mcp import agent_backend
from freelancer_mcp.backend import (
    AgentBusy,
    AlreadyBid,
    InvalidInput,
    NotFound,
    RateLimited,
    UpstreamAuthError,
    UpstreamError,
)
from freelancer_mcp.ratelimit import RateLimiter

ME = 12345678
TOKEN = "test-token"

CONFIG_YAML = f"""
profile: {{user_id: {ME}, profile_id: 1, display_name: "Dennis"}}
about_me: |
  Linux and WordPress engineer.
past_wins: []
search: {{skills: [php, wordpress, dns], results_per_skill: 20}}
filters:
  min_budget_usd: 10
  max_budget_usd: 10000
  max_bid_count: 100
  min_description_length: 20
  allowed_types: [fixed, hourly]
  client_country_allowlist: []
  client_country_blocklist: []
  require_payment_verified: false
  require_email_verified: false
bidding:
  min_hourly_rate_usd: 10
  min_fixed_bid_usd: 10
  default_position: mid
  default_milestone_percent: 50
  min_score_to_propose: 4
  max_period_days: 4
  dns_period_days: 1
claude: {{scoring_model: x, drafting_model: y, max_tokens_proposal: 400}}
auto_bid: {{enabled: true, min_score: 8}}
ai: {{provider: api, fallback_to_api: false}}
"""

GOOD_PROPOSAL = (
    "Good afternoon!\n\n"
    "I'll move your WooCommerce store to the new VPS, copy the database and uploads, update the DNS records, "
    "configure SSL and caching, then verify checkout, emails, backups and cron jobs on the new host before switching traffic over "
    "so customers never see downtime.\n\n"
    "Ready to start whenever you are."
)


def _project(pid, title, skills, budget=(100, 300), ptype="fixed", currency="USD", status="active", bids=5):
    return {
        "id": pid,
        "title": title,
        "seo_url": f"web/{title.lower().replace(' ', '-')}",
        "description": f"{title}. Full details of the work needed, long enough to pass the filters.",
        "type": ptype,
        "status": status,
        "frontend_project_status": "open" if status == "active" else "closed",
        "budget": {"minimum": budget[0], "maximum": budget[1]},
        "currency": {"code": currency},
        "bid_stats": {"bid_count": bids, "bid_avg": 150},
        "jobs": [{"name": s} for s in skills],
        "owner_id": None,
    }


class FakeFreelancer:
    """The Freelancer endpoints FreelancerClient calls, with in-memory state."""

    def __init__(self):
        self.projects = {
            1001: _project(1001, "WordPress migration to VPS", ["WordPress", "PHP"]),
            1002: _project(1002, "Fix DNS records after nameserver change", ["DNS"], budget=(30, 80)),
            1003: _project(1003, "Laravel API bug fixes", ["PHP", "Laravel"]),
            1004: _project(1004, "Hourly Linux admin", ["Linux"], budget=(15, 25), ptype="hourly"),
            1005: _project(1005, "Old closed WordPress job", ["WordPress"], status="closed"),
        }
        self.bidders: dict[int, list[int]] = {pid: [111, 222] for pid in self.projects}
        self.my_bids = [
            {"id": 9001, "project_id": 1003, "amount": 200, "period": 3, "time_submitted": 1_700_000_300,
             "award_status": "awarded", "complete_status": None, "retracted": False},
            {"id": 9002, "project_id": 1005, "amount": 90, "period": 2, "time_submitted": 1_700_000_200,
             "award_status": None, "complete_status": None, "retracted": False},
            {"id": 9003, "project_id": 1004, "amount": 20, "period": 4, "time_submitted": 1_700_000_100,
             "award_status": None, "complete_status": None, "retracted": False},
        ]  # fmt: skip
        self.threads = [
            {"id": 501, "thread": {"members": [ME, 777], "context": {"type": "project", "id": 1003}}},
        ]
        self.messages = {
            501: [
                {"id": 2, "from_user": ME, "message": "Done, please check.", "time_created": 1_700_000_900},
                {"id": 1, "from_user": 777, "message": "Can you start today?", "time_created": 1_700_000_800},
            ]
        }
        self.users = {777: {"id": 777, "username": "acme", "display_name": "Acme Ltd",
                            "location": {"country": {"name": "Kenya"}}}}  # fmt: skip
        self.requests: list[tuple[str, str]] = []
        self.posted_bids: list[dict] = []
        self.force_status: dict[str, tuple[int, dict]] = {}
        self.bid_delay = 0.0
        self._lock = threading.Lock()

    def _err(self, status, code, message):
        return JSONResponse({"status": "error", "message": message, "error_code": code}, status_code=status)

    async def handle(self, request: Request):
        path = request.url.path
        self.requests.append((request.method, path))
        if request.headers.get("freelancer-oauth-v1") != TOKEN:
            return self._err(401, "AuthServiceErrorCodes.TOKEN_INVALID", "Invalid token")
        for prefix, (status, body) in self.force_status.items():
            if path.startswith(prefix):
                return JSONResponse(body, status_code=status)
        q = request.query_params
        ok = lambda result: JSONResponse({"status": "success", "result": result})

        if path == "/api/projects/0.1/projects/active":
            terms = q.get("query", "").lower().split()
            found = [
                p for p in self.projects.values()
                if p["status"] == "active" and all(
                    t in (p["title"] + " " + " ".join(j["name"] for j in p["jobs"])).lower() for t in terms
                )
            ]  # fmt: skip
            return ok({"projects": found[: int(q.get("limit", 20))], "users": {}})
        if path == "/api/projects/0.1/projects/":
            ids = [int(i) for i in q.getlist("projects[]")]
            return ok({"projects": [self.projects[i] for i in ids if i in self.projects]})
        if path.startswith("/api/projects/0.1/projects/") and path.endswith("/bids/"):
            pid = int(path.split("/")[5])
            return ok({"bids": [{"bidder_id": b} for b in self.bidders.get(pid, [])]})
        if path.startswith("/api/projects/0.1/projects/"):
            pid = int(path.rstrip("/").split("/")[-1])
            if pid not in self.projects:
                return self._err(404, "ProjectExceptionCodes.PROJECT_NOT_FOUND", "Project not found")
            return ok(self.projects[pid])
        if path == "/api/projects/0.1/bids/" and request.method == "GET":
            return ok({"bids": self.my_bids})
        if path == "/api/projects/0.1/bids" and request.method == "POST":
            if request.headers.get("content-type") != "application/json":
                return self._err(405, None, "Method not allowed")  # the agent's CLAUDE.md trap
            body = await request.json()
            await asyncio.sleep(self.bid_delay)
            with self._lock:
                if body["bidder_id"] in self.bidders.setdefault(body["project_id"], []):
                    return self._err(
                        409, "ProjectExceptionCodes.BID_ALREADY_EXISTS", "You have already bid on this project"
                    )
                self.bidders[body["project_id"]].append(body["bidder_id"])
                self.posted_bids.append(body)
                return ok({"id": 9100 + len(self.posted_bids)})
        if path == "/api/messages/0.1/threads/":
            return ok({"threads": self.threads})
        if path == "/api/messages/0.1/messages/" and request.method == "GET":
            tid = int(q.get("threads[]"))
            return ok({"messages": self.messages.get(tid, [])[: int(q.get("limit", 50))]})
        if path == "/api/messages/0.1/messages/" and request.method == "POST":
            body = await request.json()
            msg = {"id": 99, "from_user": ME, "message": body["message"], "time_created": 1_700_001_000}
            self.messages.setdefault(body["thread_id"], []).insert(0, msg)
            return ok(msg)
        if path == "/api/users/0.1/users/":
            ids = [int(i) for i in q.getlist("users[]")]
            return ok({"users": {str(i): self.users[i] for i in ids if i in self.users}})
        return self._err(404, None, f"unexpected {request.method} {path}")


@pytest.fixture
def api():
    fake = FakeFreelancer()
    app = Starlette(routes=[Route("/{path:path}", fake.handle, methods=["GET", "POST"])])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    fake.base_url = f"http://127.0.0.1:{port}"
    yield fake
    server.should_exit = True
    thread.join(timeout=5)


CLIENT_PAGE = {
    "address": {"city": "Nairobi", "country": "Kenya", "countryCode": "ke"},
    "rating": {"average": 4.8, "reviewCount": 12},
    "verification": {"paymentVerified": True, "emailVerified": True, "depositMade": False},
    "registrationTime": 1_600_000_000_000,
    "otherEmployerJobs": [{"title": "Earlier job"}],
}


@pytest.fixture
def backend(api, tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(CONFIG_YAML)
    monkeypatch.setenv("FREELANCER_OAUTH_TOKEN", TOKEN)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "unused")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("FREELANCER_BASE_URL", api.base_url)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "projects.db"))
    # The public project page lives on www.freelancer.com, not the API host.
    monkeypatch.setattr(agent_backend.AgentFreelancerClient, "fetch_client_info_from_page",
                        lambda self, url: CLIENT_PAGE)  # fmt: skip
    return agent_backend.AgentBackend(str(tmp_path / "config.yaml"), limiter=RateLimiter(1000, 60))


def _seed(backend, project_id, status, **fields):
    from src.models import Project

    p = Project(project_id=project_id, title=f"Seeded {project_id}", description="d", seo_url="", project_type="fixed",
                budget_min=10, budget_max=100, currency_code="USD", bid_count=1, bid_avg=1, bid_min=1, bid_max=1)  # fmt: skip
    backend.storage.insert_new(p)
    backend.storage._update(project_id, status=status, **fields)


def _db_rows(backend):
    with backend.storage._conn() as c:
        return {r["project_id"]: dict(r) for r in c.execute("SELECT * FROM projects")}


# --- search ---------------------------------------------------------------------


def test_search_hides_bid_projects_and_never_writes(backend):
    _seed(backend, 1001, "bid_submitted", auto_submitted=1)
    _seed(backend, 1003, "awaiting_approval", score=7)
    before = _db_rows(backend)

    results = backend.search_projects(query="", min_budget=None, max_budget=None, skills=["php"], limit=10)
    ids = [r["id"] for r in results]
    assert 1001 not in ids, "already bid on according to SQLite"
    assert 1003 in ids
    by_id = {r["id"]: r for r in results}
    assert by_id[1003]["agent"] == {"status": "awaiting_approval", "score": 7}
    assert by_id[1003]["budget"] == {"min": 100.0, "max": 300.0, "currency": "USD"}
    # The poller must still be able to process everything the search saw.
    assert _db_rows(backend) == before


def test_search_filters_budget_and_requires_criteria(backend):
    results = backend.search_projects(query="", min_budget=200, max_budget=None, skills=["php", "dns"], limit=10)
    assert {r["id"] for r in results} == {1001, 1003}  # the DNS job tops out at 80
    with pytest.raises(InvalidInput):
        backend.search_projects(query="", min_budget=None, max_budget=None, skills=[], limit=10)


# --- get_project ------------------------------------------------------------------


def test_get_project_includes_client_and_rules(backend, api):
    p = backend.get_project(1002)
    assert p["client"]["country_code"] == "KE"
    assert p["client"]["rating"] == 4.8 and p["client"]["reviews"] == 12
    assert p["client"]["payment_verified"] is True
    assert p["client"]["hire_rate"] is None and "hire_rate_note" in p["client"]
    assert p["bid_count"] == 5
    assert p["already_bid"] is False
    assert p["bid_rules"]["max_period_days"] == 1, "DNS work ships in one day"
    assert p["bid_rules"]["min_amount"] == 10 and p["bid_rules"]["max_amount"] == 80

    api.bidders[1001].append(ME)
    assert backend.get_project(1001)["already_bid"] is True
    with pytest.raises(NotFound):
        backend.get_project(4242)


# --- place_bid --------------------------------------------------------------------


def _bid(backend, pid=1001, amount=250.0, days=3, text=GOOD_PROPOSAL, dry_run=False):
    return backend.place_bid(project_id=pid, amount=amount, period_days=days, description=text, dry_run=dry_run)


def test_dry_run_checks_but_sends_and_writes_nothing(backend, api):
    result = _bid(backend, dry_run=True)
    assert result["dry_run"] is True and result["submitted"] is False
    assert result["would_submit"]["milestone_percent"] == 100
    assert result["style_warnings"] == []
    assert api.posted_bids == []
    assert _db_rows(backend) == {}


def test_bid_is_submitted_like_the_other_paths_and_logged(backend, api):
    result = _bid(backend)
    assert result["submitted"] is True
    assert api.posted_bids == [{
        "project_id": 1001, "bidder_id": ME, "profile_id": 1, "amount": 250.0, "period": 3,
        "milestone_percentage": 100, "description": GOOD_PROPOSAL,
    }]  # fmt: skip
    row = _db_rows(backend)[1001]
    assert row["status"] == "bid_submitted"
    assert row["submitted_bid_id"] == result["bid_id"]
    assert (row["suggested_amount"], row["suggested_period"], row["suggested_milestone"]) == (250.0, 3, 100)
    assert row["proposal_text"] == GOOD_PROPOSAL
    assert row["auto_submitted"] == 0

    with pytest.raises(AlreadyBid):
        _bid(backend)
    assert len(api.posted_bids) == 1


@pytest.mark.parametrize(
    ("pid", "amount", "days", "needle"),
    [
        (1001, 250.0, 5, "Ask the owner to approve 4"),  # 4-day ceiling
        (1002, 50.0, 2, "Ask the owner to approve 1"),  # DNS: one day
        (1001, 5.0, 3, "Ask the owner to approve 10"),  # fixed-bid floor
        (1001, 900.0, 3, "Ask the owner to approve 300"),  # project's max budget
    ],
)
def test_bid_rules_are_enforced_not_silently_changed(backend, api, pid, amount, days, needle):
    with pytest.raises(InvalidInput, match=needle):
        _bid(backend, pid=pid, amount=amount, days=days)
    assert api.posted_bids == []


def test_style_warnings_flag_departures_from_the_owner_rules(backend):
    result = _bid(backend, dry_run=True, text="Hi - can I help? $200\n\nDennis")
    warnings = " ".join(result["style_warnings"])
    for needle in ("words", "paragraphs", "dash", "question", "price", "signature"):
        assert needle in warnings


def test_refuses_when_freelancer_already_shows_my_bid(backend, api):
    api.bidders[1001].append(ME)
    with pytest.raises(AlreadyBid, match="Freelancer already shows"):
        _bid(backend)
    assert api.posted_bids == []


def test_refuses_while_the_poller_is_processing(backend, api):
    _seed(backend, 1001, "new")
    with pytest.raises(AgentBusy):
        _bid(backend)
    # A row stranded at 'new' long ago (the known poller bug) is fine to bid on.
    with backend.storage._conn() as c:
        c.execute("UPDATE projects SET updated_at = ? WHERE project_id = 1001", (int(time.time()) - 86400,))
    assert _bid(backend)["submitted"] is True


def test_closed_project_is_refused(backend):
    with pytest.raises(InvalidInput, match="no longer open"):
        _bid(backend, pid=1005)


def test_concurrent_bids_on_one_project_submit_once(backend, api):
    api.bid_delay = 0.3
    outcomes: list[object] = []

    def attempt():
        try:
            outcomes.append(_bid(backend))
        except AlreadyBid as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(api.posted_bids) == 1
    assert sum(isinstance(o, dict) for o in outcomes) == 1
    assert sum(isinstance(o, AlreadyBid) for o in outcomes) == 3
    assert _db_rows(backend)[1001]["status"] == "bid_submitted"


def test_another_path_bidding_between_check_and_claim_is_caught(backend, api, monkeypatch):
    """The poller or portal claims the row after our checks but before our claim."""
    real_insert = backend.storage.insert_new

    def insert_then_portal_bids(p):
        real_insert(p)
        backend.storage.mark_approved(p.project_id)

    monkeypatch.setattr(backend.storage, "insert_new", insert_then_portal_bids)
    with pytest.raises(AlreadyBid, match="Another path"):
        _bid(backend)
    assert api.posted_bids == []


# --- Freelancer errors -------------------------------------------------------------


def test_bid_failure_is_recorded_like_the_portal(backend, api):
    api.force_status["/api/projects/0.1/bids"] = (
        403,
        {
            "status": "error",
            "message": "You must sign the NDA first.",
            "error_code": "ProjectExceptionCodes.NDA_NOT_SIGNED",
        },
    )
    with pytest.raises(UpstreamError, match="NDA"):
        _bid(backend)
    row = _db_rows(backend)[1001]
    assert row["status"] == "bid_failed"
    assert "NDA_NOT_SIGNED" in row["error_message"]  # the portal parses this for its Retry button
    # A failed bid can be tried again once the problem is fixed.
    del api.force_status["/api/projects/0.1/bids"]
    assert _bid(backend)["submitted"] is True


def test_duplicate_bid_from_freelancer_maps_to_already_bid(backend, api, monkeypatch):
    # Freelancer accepted a bid our bidders check could not see yet.
    monkeypatch.setattr(backend.fl, "get_existing_bid_user_ids", lambda pid: [])
    api.bidders[1001].append(ME)
    with pytest.raises(AlreadyBid):
        _bid(backend)


def test_expired_token_and_rate_limits_are_actionable(backend, api, monkeypatch):
    backend.fl.session.headers["Freelancer-OAuth-V1"] = "expired"
    with pytest.raises(UpstreamAuthError, match="FREELANCER_OAUTH_TOKEN"):
        backend.get_project(1001)
    backend.fl.session.headers["Freelancer-OAuth-V1"] = TOKEN

    # The agent's client retries 429s with backoff; skip the waits here.
    from tenacity import wait_none

    for name in ("_get", "_post"):
        fn = getattr(agent_backend.FreelancerClient, name)
        monkeypatch.setattr(agent_backend.FreelancerClient, name, fn.retry_with(wait=wait_none()))
    api.force_status["/api/projects/0.1/projects/"] = (429, {"status": "error", "message": "slow down"})
    with pytest.raises(RateLimited):
        backend.get_project(1001)
    calls = len(api.requests)
    with pytest.raises(RateLimited, match="Try again"):  # backed off: no request at all
        backend.get_project(1001)
    assert len(api.requests) == calls


# --- bids, messages -----------------------------------------------------------------


def test_list_my_bids_reads_freelancer_status(backend, api):
    _seed(backend, 1004, "bid_submitted", auto_submitted=1)
    everything = {b["bid_id"]: b for b in backend.list_my_bids("all")}
    assert everything[9001]["status"] == "awarded"
    assert everything[9002]["status"] == "rejected"  # project closed without an award
    assert everything[9003]["status"] == "active"
    assert everything[9003]["auto_submitted"] is True
    assert everything[9001]["title"] == "Laravel API bug fixes"
    assert everything[9003]["currency"] == "USD"
    assert [b["bid_id"] for b in backend.list_my_bids("active")] == [9003]
    assert [b["bid_id"] for b in backend.list_my_bids("awarded")] == [9001]


def test_messages_by_project_and_thread(backend):
    by_project = backend.get_messages(thread_id=None, project_id=1003)
    assert by_project["thread_id"] == 501
    assert [m["text"] for m in by_project["messages"]] == ["Can you start today?", "Done, please check."]
    assert by_project["messages"][0]["sender"] == "Acme Ltd"
    assert by_project["messages"][1]["from_me"] is True
    assert by_project["with"]["country"] == "Kenya"
    assert backend.get_messages(thread_id=501, project_id=None)["messages"] == by_project["messages"]
    with pytest.raises(NotFound):
        backend.get_messages(thread_id=None, project_id=1001)


def test_send_message_dry_run_and_live(backend, api):
    dry = backend.send_message(thread_id=501, text="On it.", dry_run=True)
    assert dry["sent"] is False
    assert len(api.messages[501]) == 2
    sent = backend.send_message(thread_id=501, text="On it.", dry_run=False)
    assert sent["sent"] is True and sent["message"]["text"] == "On it."
    assert api.messages[501][0]["message"] == "On it."


# --- through the MCP server ---------------------------------------------------------


def test_tools_end_to_end_through_mcp(backend, tmp_path):
    import anyio
    from mcp import Client

    from freelancer_mcp.config import Settings
    from mcp_server import build_server

    settings = Settings(
        public_url="http://127.0.0.1:1", host="127.0.0.1", port=1, backend="agent", agent_config="config.yaml",
        dry_run=False, max_bid_amount=None, api_max_calls=100, api_period_seconds=60, auth_disabled=True,
        auth_db_path=tmp_path / "auth.db", owner_password_hash="", owner_totp_secret="",
        allow_loopback_redirects=False, access_token_ttl=60, refresh_token_ttl=60,
    )  # fmt: skip

    async def run():
        async with Client(build_server(settings, backend)) as client:
            found = await client.call_tool("search_projects", {"query": "wordpress"})
            assert not found.is_error, found.content[0].text
            assert [p["id"] for p in found.structured_content["result"]] == [1001]
            bad = await client.call_tool(
                "place_bid", {"project_id": 1001, "amount": 250, "period_days": 9, "description": GOOD_PROPOSAL}
            )
            assert bad.is_error and bad.content[0].text.count("invalid_input") == 1
            ok = await client.call_tool(
                "place_bid", {"project_id": 1001, "amount": 250, "period_days": 4, "description": GOOD_PROPOSAL}
            )
            assert not ok.is_error, ok.content[0].text
            again = await client.call_tool(
                "place_bid", {"project_id": 1001, "amount": 250, "period_days": 4, "description": GOOD_PROPOSAL}
            )
            assert again.is_error and "already_bid" in again.content[0].text

    anyio.run(run)
    assert json.loads(json.dumps(_db_rows(backend)[1001]))["status"] == "bid_submitted"


def test_unexpected_submit_crash_never_leaves_the_row_claimed(backend, api, monkeypatch):
    def broken_submit(**kwargs):
        raise KeyError("id")

    monkeypatch.setattr(backend.fl, "submit_bid", broken_submit)
    with pytest.raises(KeyError):
        _bid(backend)
    assert _db_rows(backend)[1001]["status"] == "bid_failed"
    monkeypatch.delattr(backend.fl, "submit_bid")  # back to the real client method
    assert _bid(backend)["submitted"] is True
