"""Adapter from the MCP tools to the bidding agent's own modules.

Runs from the agent's directory (next to poller.py and portal.py) and reuses its
config loader, Freelancer client, SQLite storage, bid rules and error parser, so
nothing about Freelancer.com is implemented twice. No agent file is modified.

Bidding is the agent's fifth submit path (after the pipeline's auto-bid, the
portal's two endpoints and the Telegram bot), so it enforces the same rules as
the other four (see the agent's CLAUDE.md): the period clamp, the amount floors
and the 100% milestone. Where the other paths clamp silently, this one refuses
and says what is allowed, because the owner approved the exact numbers in chat.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any

import requests
from portal import _parse_fl_error
from src.config import load_config
from src.filters import filter_project, has_skill_overlap, is_dns
from src.freelancer_client import FreelancerClient, FreelancerError
from src.models import Project
from src.pipeline import _enforce_floors, enforce_period_days
from src.storage import Storage

from freelancer_mcp.backend import (
    ENGAGED_STATUSES,
    AgentBusy,
    AlreadyBid,
    BackendError,
    BidStatus,
    InvalidInput,
    NotFound,
    RateLimited,
    UpstreamAuthError,
    UpstreamError,
    proposal_style_warnings,
)
from freelancer_mcp.ratelimit import RateLimiter

log = logging.getLogger(__name__)

# A row the poller inserted this recently, still at status 'new', is being scored right
# now and may be auto-bid within minutes. Older 'new' rows are the stranded ones the
# agent's CLAUDE.md describes, and are safe to bid on.
POLLER_BUSY_SECONDS = 900


class AgentFreelancerClient(FreelancerClient):
    """The agent's client plus the two read calls the MCP tools need.

    Uses the parent's authenticated session, retries and project parser unchanged.
    """

    def get_project(self, project_id: int) -> tuple[Project, dict]:
        """GET /api/projects/0.1/projects/{id}/ -> (parsed Project, raw project dict)."""
        data = self._get(
            f"/api/projects/0.1/projects/{project_id}/",
            params={"full_description": "true", "job_details": "true"},
        )
        raw = data.get("result") or {}
        if not raw.get("id"):
            raise FreelancerError(f"GET /api/projects/0.1/projects/{project_id}/ -> 404: no project in response")
        return self._to_project(raw, {}), raw

    def get_projects(self, project_ids: list[int]) -> dict[int, dict]:
        """GET /api/projects/0.1/projects/?projects[]=... -> {project_id: raw project dict}."""
        if not project_ids:
            return {}
        data = self._get(
            "/api/projects/0.1/projects/",
            params={"projects[]": list(project_ids), "limit": len(project_ids)},
        )
        projects = (data.get("result") or {}).get("projects") or []
        return {int(p["id"]): p for p in projects if p.get("id")}


def _is_open(raw: dict) -> bool:
    status = raw.get("status")
    frontend = raw.get("frontend_project_status")
    return status in (None, "active") and frontend in (None, "open")


def _map_freelancer_error(raw: str) -> BackendError:
    parsed = _parse_fl_error(raw)
    code, status, reason = parsed["code"], parsed["status"], parsed["reason"]
    if code == "AuthServiceErrorCodes.TOKEN_INVALID" or status == 401:
        return UpstreamAuthError(f"{reason} Update FREELANCER_OAUTH_TOKEN in the agent's .env.")
    if code == "ProjectExceptionCodes.BID_ALREADY_EXISTS":
        return AlreadyBid(reason)
    if code == "ProjectExceptionCodes.PROJECT_NOT_FOUND" or status == 404:
        return NotFound(reason)
    return UpstreamError(f"{reason} ({code})" if code else reason)


class AgentBackend:
    def __init__(self, config_path: str = "config.yaml", limiter: RateLimiter | None = None):
        self.cfg = load_config(config_path)
        self.fl = AgentFreelancerClient(self.cfg.freelancer_base_url, self.cfg.freelancer_oauth_token)
        self.storage = Storage(self.cfg.db_path)
        self.limiter = limiter or RateLimiter(30, 60)
        self.display_name = self.cfg.profile.display_name

    # --- plumbing -----------------------------------------------------------

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except requests.RequestException as exc:
            if "429" in str(exc):
                self.limiter.back_off(60)
                raise RateLimited(
                    "Freelancer answered 429 (rate limit) even after retries. Wait about a minute.",
                    retry_after=60,
                ) from exc
            raise UpstreamError(f"Could not reach Freelancer.com: {exc}") from exc
        except FreelancerError as exc:
            raise _map_freelancer_error(str(exc)) from exc

    def _api(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self.limiter.acquire()
        return self._call(fn, *args, **kwargs)

    def _rows(self, project_ids: Iterable[int]) -> dict[int, Any]:
        ids = list(dict.fromkeys(project_ids))
        rows: dict[int, Any] = {}
        with self.storage._conn() as c:
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                marks = ",".join("?" * len(chunk))
                for r in c.execute(f"SELECT * FROM projects WHERE project_id IN ({marks})", chunk):
                    rows[r["project_id"]] = r
        return rows

    @staticmethod
    def _agent_view(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        view: dict[str, Any] = {"status": row["status"], "score": row["score"]}
        if row["filter_reason"]:
            view["filter_reason"] = row["filter_reason"]
        if row["status"] == "bid_submitted":
            view["auto_submitted"] = bool(row["auto_submitted"])
        return view

    def _bid_rules(self, project: Project) -> dict[str, Any]:
        bidding = self.cfg.bidding
        dns = is_dns(project.title, project.description, project.skills)
        return {
            # The floor, capped by the project's max budget, exactly as _enforce_floors applies it.
            "min_amount": _enforce_floors(SimpleNamespace(suggested_amount=0.0), project, self.cfg),
            "max_amount": project.budget_max or None,
            "currency": project.currency_code,
            "amount_is_hourly_rate": project.project_type == "hourly",
            "period_days": f"exactly {bidding.dns_period_days} (DNS work)"
            if dns
            else f"1 to {bidding.max_period_days}",
            "max_period_days": bidding.dns_period_days if dns else bidding.max_period_days,
            "milestone_percent": 100,
        }

    # --- tools --------------------------------------------------------------

    def search_projects(self, *, query, min_budget, max_budget, skills, limit):
        queries = [query] if query else skills[:5]
        if not queries:
            raise InvalidInput("give a query or at least one skill")
        fetch = min(100, max(limit * 3, 20))
        found: dict[int, Project] = {}
        for q in queries:
            for p in self._api(self.fl.search_projects, q, fetch):
                found.setdefault(p.project_id, p)

        rows = self._rows(found)
        results = []
        for p in found.values():
            row = rows.get(p.project_id)
            if row is not None and row["status"] in ENGAGED_STATUSES:
                continue
            if skills and not has_skill_overlap(p.skills, skills):
                continue
            if min_budget is not None and p.budget_max and p.budget_max < min_budget:
                continue
            if max_budget is not None and p.budget_min > max_budget:
                continue
            results.append(
                {
                    "id": p.project_id,
                    "title": p.title,
                    "url": p.seo_url,
                    "type": p.project_type,
                    "budget": {"min": p.budget_min, "max": p.budget_max, "currency": p.currency_code},
                    "skills": p.skills,
                    "bid_count": p.bid_count,
                    "bid_avg": p.bid_avg,
                    # The search API hides client country and verification under this token;
                    # get_project reads them from the public project page instead.
                    "agent": self._agent_view(row),
                    "agent_rule_filter": None if row is not None else filter_project(p, self.cfg.filters),
                }
            )
            if len(results) >= limit:
                break
        return results

    def get_project(self, project_id):
        project, raw = self._api(self.fl.get_project, project_id)
        bidders = self._api(self.fl.get_existing_bid_user_ids, project_id)
        # Public page scrape, not an API call; returns None when the page is unavailable.
        info = self.fl.fetch_client_info_from_page(project.seo_url)
        row = self.storage.get(project_id)

        client: dict[str, Any] = {"hire_rate": None}
        if info:
            addr = info.get("address") or {}
            rating = info.get("rating") or {}
            verification = info.get("verification") or {}
            registered = info.get("registrationTime") or 0
            client.update(
                country=addr.get("country"),
                country_code=(addr.get("countryCode") or "").upper() or None,
                city=addr.get("city"),
                rating=rating.get("average"),
                reviews=rating.get("reviewCount"),
                payment_verified=bool(verification.get("paymentVerified")),
                email_verified=bool(verification.get("emailVerified")),
                deposit_made=bool(verification.get("depositMade")),
                member_since=int(registered / 1000) if registered else None,
                other_jobs=[j.get("title") for j in (info.get("otherEmployerJobs") or [])[:5]],
            )
        else:
            client["note"] = "The client's public project page could not be read."
        client["hire_rate_note"] = "Freelancer does not expose hire rate to this API token or on the public page."

        agent = self._agent_view(row)
        if agent is not None:
            agent["score_reasoning"] = row["score_reasoning"]
            if row["proposal_text"]:
                agent["draft"] = {
                    "text": row["proposal_text"],
                    "amount": row["suggested_amount"],
                    "period_days": row["suggested_period"],
                }

        return {
            "id": project.project_id,
            "title": project.title,
            "url": project.seo_url,
            "type": project.project_type,
            "open_for_bids": _is_open(raw),
            "description": project.description,
            "budget": {"min": project.budget_min, "max": project.budget_max, "currency": project.currency_code},
            "skills": project.skills,
            "bid_count": project.bid_count,
            "bid_avg": project.bid_avg,
            "already_bid": self.cfg.profile.user_id in bidders
            or (row is not None and row["status"] in ENGAGED_STATUSES),
            "client": client,
            "agent": agent,
            "bid_rules": self._bid_rules(project),
        }

    def place_bid(self, *, project_id, amount, period_days, description, dry_run):
        amount = round(amount, 2)  # what is checked is exactly what is sent
        row = self.storage.get(project_id)
        self._refuse_if_engaged(row)
        if row is not None and row["status"] == "new" and time.time() - row["updated_at"] < POLLER_BUSY_SECONDS:
            raise AgentBusy(
                "The auto-agent picked this project up in the last few minutes and may bid on it itself. "
                "Check again in about 10 minutes with get_project."
            )

        project, raw = self._api(self.fl.get_project, project_id)
        if not _is_open(raw):
            raise InvalidInput(f"Project {project_id} is no longer open for bids (status: {raw.get('status')}).")
        if self.cfg.profile.user_id in self._api(self.fl.get_existing_bid_user_ids, project_id):
            raise AlreadyBid(f"Freelancer already shows a bid from you on project {project_id}. Not bidding again.")

        rules = self._bid_rules(project)
        allowed_period = enforce_period_days(period_days, project, self.cfg)
        if allowed_period != period_days:
            raise InvalidInput(
                f"period_days {period_days} breaks the agent's rule for this project: {rules['period_days']} days. "
                f"Ask the owner to approve {allowed_period}."
            )
        allowed_amount = _enforce_floors(SimpleNamespace(suggested_amount=amount), project, self.cfg)
        if abs(allowed_amount - amount) > 0.005:
            raise InvalidInput(
                f"amount {amount} {project.currency_code} is outside the agent's limits for this project "
                f"(at least {rules['min_amount']}, at most {rules['max_amount']}). "
                f"Ask the owner to approve {allowed_amount}."
            )

        bid = {
            "project_id": project_id,
            "title": project.title,
            "url": project.seo_url,
            "amount": amount,
            "currency": project.currency_code,
            "period_days": period_days,
            "milestone_percent": 100,
            "description": description,
        }
        warnings = proposal_style_warnings(description, self.display_name)
        if dry_run:
            return {"dry_run": True, "submitted": False, "would_submit": bid, "style_warnings": warnings}

        # Take the API budget first, so a local rate limit never leaves a claimed row behind.
        self.limiter.acquire()
        self._claim(project, amount, period_days, description)
        try:
            bid_id = self._call(
                self.fl.submit_bid,
                project_id=project_id,
                bidder_id=self.cfg.profile.user_id,
                profile_id=self.cfg.profile.profile_id,
                amount=float(amount),
                period_days=int(period_days),
                milestone_percent=100,
                description=description,
            )
        except Exception as exc:
            # Same bookkeeping as the portal: the raw error is kept for its history screen and Retry
            # button, and the row never stays at 'approved' (which would block every later bid).
            cause = exc.__cause__ if isinstance(exc, BackendError) and exc.__cause__ else exc
            self.storage.mark_bid_failed(project_id, str(cause))
            if isinstance(exc, AlreadyBid):
                # The agent's client retries a POST that timed out, so the first attempt may have landed.
                raise AlreadyBid(
                    f"{exc.message} If an earlier attempt timed out, that bid did go through; check list_my_bids."
                ) from exc
            raise
        self.storage.mark_bid_submitted(project_id, bid_id)
        log.info("MCP bid placed on %d: %s %s, %dd, bid_id=%s", project_id, amount, project.currency_code,
                 period_days, bid_id)  # fmt: skip
        return {"dry_run": False, "submitted": True, "bid_id": bid_id, **bid, "style_warnings": warnings}

    def _refuse_if_engaged(self, row: Any) -> None:
        if row is not None and row["status"] in ENGAGED_STATUSES:
            how = "auto-bid by the agent" if row["auto_submitted"] else "bid already placed"
            amount = row["suggested_amount"]
            raise AlreadyBid(
                f"Project {row['project_id']}: {how}"
                + (f" ({amount} {row['currency_code']})" if amount is not None else "")
                + ". Not bidding again."
            )

    def _claim(self, project: Project, amount: float, period_days: int, description: str) -> None:
        """Atomically move the row to 'approved', unless another path got there first.

        One conditional UPDATE under SQLite's write lock: whichever of the poller,
        portal, bot or this server claims the row first wins, the rest see rowcount 0.
        """
        self.storage.insert_new(project)  # INSERT OR IGNORE, the row the poller would write
        marks = ",".join("?" * len(ENGAGED_STATUSES))
        with self.storage._conn() as c:
            claimed = c.execute(
                f"""UPDATE projects SET status = 'approved', proposal_text = ?, suggested_amount = ?,
                        suggested_period = ?, suggested_milestone = 100, error_message = NULL, updated_at = ?
                    WHERE project_id = ? AND status NOT IN ({marks})""",
                (description, amount, period_days, int(time.time()), project.project_id, *ENGAGED_STATUSES),
            ).rowcount
        if claimed != 1:
            raise AlreadyBid(
                f"Another path (auto-agent, portal or Telegram) started a bid on project {project.project_id} "
                "a moment ago. Not bidding again."
            )

    def list_my_bids(self, status: BidStatus):
        bids = self._api(self.fl.get_my_bids, self.cfg.profile.user_id, limit=100)
        bids.sort(key=lambda b: b.get("time_submitted") or 0, reverse=True)
        ids = [int(b["project_id"]) for b in bids if b.get("project_id")]
        projects = self._api(self.fl.get_projects, ids[:100]) if ids else {}
        rows = self._rows(ids)

        results = []
        for b in bids:
            pid = int(b.get("project_id") or 0)
            raw = projects.get(pid) or {}
            row = rows.get(pid)
            bid_status = _bid_status(b, raw)
            if status != "all" and bid_status != status:
                continue
            seo = raw.get("seo_url")
            results.append(
                {
                    "bid_id": b.get("id"),
                    "project_id": pid,
                    "title": raw.get("title") or (row["title"] if row is not None else None),
                    "url": f"https://www.freelancer.com/projects/{seo}"
                    if seo
                    else (row["seo_url"] if row is not None else None),
                    "amount": b.get("amount"),
                    "currency": (raw.get("currency") or {}).get("code")
                    or (row["currency_code"] if row is not None else None),
                    "period_days": b.get("period"),
                    "status": bid_status,
                    "award_status": b.get("award_status"),
                    "project_status": raw.get("frontend_project_status") or raw.get("status"),
                    "submitted_at": b.get("time_submitted"),
                    "auto_submitted": bool(row["auto_submitted"]) if row is not None else False,
                }
            )
            if len(results) >= 50:
                break
        return results

    def get_messages(self, *, thread_id, project_id):
        me = self.cfg.profile.user_id
        context_project = project_id
        if thread_id is None:
            threads = self._api(self.fl.get_threads, limit=50)
            match = None
            for t in threads:
                context = (t.get("thread") or {}).get("context") or {}
                if context.get("type") == "project" and str(context.get("id")) == str(project_id):
                    match = t
                    break
            if match is None:
                raise NotFound(f"No message thread for project {project_id} among your 50 most recent threads.")
            thread_id = int(match["id"])

        raw = self._api(self.fl.get_thread_messages, thread_id, limit=50)
        sender_ids = {int(m["from_user"]) for m in raw if m.get("from_user")}
        try:
            users = self._api(self.fl.get_users, sorted(sender_ids)) if sender_ids else {}
        except BackendError as exc:
            log.warning("Could not load message senders for thread %s: %s", thread_id, exc.message)
            users = {}

        def name(uid: int) -> str:
            u = users.get(uid) or {}
            return u.get("display_name") or u.get("username") or f"User #{uid}"

        messages = [
            {
                "id": m.get("id"),
                "from_me": int(m.get("from_user") or 0) == me,
                "sender": "me" if int(m.get("from_user") or 0) == me else name(int(m.get("from_user") or 0)),
                "text": m.get("message") or "",
                "sent_at": m.get("time_created"),
            }
            for m in reversed(raw)  # Freelancer returns newest first
        ]
        other = next((uid for uid in sender_ids if uid != me), None)
        other_user = (users.get(other) or {}) if other else {}
        return {
            "thread_id": thread_id,
            "project_id": context_project,
            "with": {
                "name": name(other) if other else None,
                "username": other_user.get("username"),
                "country": ((other_user.get("location") or {}).get("country") or {}).get("name"),
            },
            "messages": messages,
        }

    def send_message(self, *, thread_id, text, dry_run):
        if dry_run:
            self._api(self.fl.get_thread_messages, thread_id, limit=1)  # proves the thread is reachable
            return {"dry_run": True, "sent": False, "would_send": {"thread_id": thread_id, "text": text}}
        result = self._api(self.fl.send_message, thread_id, text)
        return {
            "dry_run": False,
            "sent": True,
            "thread_id": thread_id,
            "message": {
                "id": result.get("id"),
                "text": result.get("message", text),
                "sent_at": result.get("time_created"),
            },
        }


def _bid_status(bid: dict, project: dict) -> str:
    """Same reading of Freelancer's bid fields as the portal's history screen, plus closed projects."""
    award = bid.get("award_status")
    if bid.get("retracted"):
        return "retracted"
    if award == "awarded" or bid.get("complete_status") == "complete":
        return "awarded"
    if award in ("rejected", "revoked", "canceled", "declined"):
        return "rejected"
    if project and not _is_open(project):
        return "rejected"  # project closed or awarded to someone else
    return "active"
