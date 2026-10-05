"""The interface the MCP tools call, and the errors they turn into tool messages.

`AgentBackend` (agent_backend.py) adapts the bidding agent's own Freelancer client,
config and SQLite storage to this interface. `FakeBackend` serves sample data in the
same shapes so every tool can be exercised in the MCP Inspector without touching
the live account.

Backend methods are synchronous because they wrap the agent's existing code; the
server runs them in a worker thread.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Literal, Protocol

BidStatus = Literal["active", "awarded", "rejected", "all"]

# Rows in these states already carry a bid (or one in flight). Same meaning as in the
# agent's storage.py state machine.
ENGAGED_STATUSES = ("approved", "bid_submitted")


class BackendError(Exception):
    """A failure Claude can act on. `code` is a stable machine-readable tag."""

    code = "error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(BackendError):
    code = "not_found"


class InvalidInput(BackendError):
    code = "invalid_input"


class AlreadyBid(BackendError):
    code = "already_bid"


class AgentBusy(BackendError):
    """The auto-agent is processing this project right now."""

    code = "agent_busy"


class RateLimited(BackendError):
    code = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class UpstreamAuthError(BackendError):
    """The Freelancer OAuth token is missing, expired or lacks a scope."""

    code = "freelancer_auth"


class UpstreamError(BackendError):
    """Freelancer.com rejected the request or is unavailable."""

    code = "freelancer_error"


class Backend(Protocol):
    def search_projects(
        self,
        *,
        query: str,
        min_budget: float | None,
        max_budget: float | None,
        skills: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Active projects, excluding any already bid on according to the agent's SQLite.
        Must not write to the database: the poller still has to process what it finds."""
        ...

    def get_project(self, project_id: int) -> dict[str, Any]: ...

    def place_bid(
        self, *, project_id: int, amount: float, period_days: int, description: str, dry_run: bool
    ) -> dict[str, Any]:
        """Submit a bid and log it to the agent's projects table.

        Enforces the same rules as the agent's other submit paths, refuses with
        `AlreadyBid` when a bid exists or is in flight, and claims the row atomically
        before submitting so the agent and this server never bid on the same project.
        With `dry_run`, run every check and return what would be sent, writing nothing.
        """
        ...

    def list_my_bids(self, status: BidStatus) -> list[dict[str, Any]]: ...

    def get_messages(self, *, thread_id: int | None, project_id: int | None) -> dict[str, Any]: ...

    def send_message(self, *, thread_id: int, text: str, dry_run: bool) -> dict[str, Any]: ...


def proposal_style_warnings(text: str, display_name: str | None = None) -> list[str]:
    """The owner's proposal rules (the agent's DRAFTING_SYSTEM), checked loosely.

    Warnings only: the owner approved the text, so the server never rewrites or blocks it.
    """
    warnings = []
    words = len(text.split())
    if not 50 <= words <= 100:
        warnings.append(f"{words} words; the agent's proposals are 50 to 100")
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) != 3:
        warnings.append(f"{len(paragraphs)} paragraphs; the agent's proposals have exactly 3")
    if "—" in text or "–" in text or " - " in text:
        warnings.append("contains a dash; the rules allow hyphens only inside compound words")
    if "?" in text:
        warnings.append("contains a question; the rules say never ask the client anything")
    if "$" in text:
        warnings.append("mentions a price; pricing belongs in the amount only")
    if display_name and text.rstrip().lower().endswith(display_name.lower()):
        warnings.append("ends with a signature; the rules say no sign-off")
    return warnings


class FakeBackend:
    """In-memory sample data with the same shapes and rules as AgentBackend."""

    display_name = "Dennis"
    max_period_days = 4

    def __init__(self) -> None:
        now = int(time.time())
        self._lock = threading.Lock()
        self._projects: dict[int, dict[str, Any]] = {
            40000001: {
                "id": 40000001,
                "title": "Build a Telegram bot that posts daily sales reports",
                "url": "https://www.freelancer.com/projects/python/telegram-bot-sales-reports",
                "type": "fixed",
                "status": "active",
                "budget": {"min": 250.0, "max": 750.0, "currency": "USD"},
                "skills": ["Python", "Telegram API", "SQLite"],
                "bid_count": 14,
                "bid_avg": 480.0,
                "description": "We need a bot that reads our Postgres sales table every morning "
                "and posts a summary chart to a Telegram group.",
                "client": {
                    "country": "United Kingdom",
                    "country_code": "GB",
                    "city": "London",
                    "rating": 4.9,
                    "reviews": 37,
                    "payment_verified": True,
                    "email_verified": True,
                    "deposit_made": True,
                    "member_since": now - 3 * 365 * 86400,
                    "hire_rate": None,
                    "other_jobs": [],
                },
            },
            40000002: {
                "id": 40000002,
                "title": "Fix DNS records after moving to Cloudflare",
                "url": "https://www.freelancer.com/projects/dns/fix-dns-records-cloudflare",
                "type": "fixed",
                "status": "active",
                "budget": {"min": 30.0, "max": 250.0, "currency": "USD"},
                "skills": ["DNS", "Cloudflare", "Web Hosting"],
                "bid_count": 9,
                "bid_avg": 95.0,
                "description": "Email stopped working after we changed nameservers. Need MX, SPF and DKIM fixed.",
                "client": {
                    "country": "Kenya",
                    "country_code": "KE",
                    "city": "Nairobi",
                    "rating": None,
                    "reviews": 0,
                    "payment_verified": False,
                    "email_verified": True,
                    "deposit_made": False,
                    "member_since": now - 20 * 86400,
                    "hire_rate": None,
                    "other_jobs": [],
                },
            },
            40000003: {
                "id": 40000003,
                "title": "WordPress site migration to a new host",
                "url": "https://www.freelancer.com/projects/wordpress/site-migration-new-host",
                "type": "fixed",
                "status": "active",
                "budget": {"min": 100.0, "max": 300.0, "currency": "USD"},
                "skills": ["WordPress", "PHP", "Server Migration"],
                "bid_count": 22,
                "bid_avg": 180.0,
                "description": "Move a WooCommerce site from shared hosting to a VPS with zero downtime.",
                "client": {
                    "country": "Germany",
                    "country_code": "DE",
                    "city": "Berlin",
                    "rating": 4.6,
                    "reviews": 12,
                    "payment_verified": True,
                    "email_verified": True,
                    "deposit_made": True,
                    "member_since": now - 5 * 365 * 86400,
                    "hire_rate": None,
                    "other_jobs": [],
                },
            },
        }
        # Stands in for the agent's projects table.
        self._rows: dict[int, dict[str, Any]] = {
            40000003: {
                "status": "bid_submitted",
                "score": 9,
                "auto_submitted": 1,
                "bid_id": 70000001,
                "amount": 220.0,
                "period_days": 3,
                "submitted_at": now - 20 * 3600,
            }
        }
        self._threads: dict[int, dict[str, Any]] = {
            80000001: {
                "thread_id": 80000001,
                "project_id": 40000003,
                "with": {"name": "Bookly GmbH", "username": "bookly_io", "country": "Germany"},
                "messages": [
                    {
                        "id": 1,
                        "from_me": False,
                        "sender": "Bookly GmbH",
                        "text": "Hi, can you start next week?",
                        "sent_at": now - 2 * 3600,
                    }
                ],
            }
        }
        self._next_bid_id = 70000002
        self._next_message_id = 2

    def _is_dns(self, project: dict[str, Any]) -> bool:
        return "dns" in project["title"].lower().split()

    def _bid_rules(self, project: dict[str, Any]) -> dict[str, Any]:
        dns = self._is_dns(project)
        return {
            "min_amount": min(10.0, project["budget"]["max"]),
            "max_amount": project["budget"]["max"],
            "currency": project["budget"]["currency"],
            "amount_is_hourly_rate": project["type"] == "hourly",
            "period_days": "exactly 1 (DNS work)" if dns else f"1 to {self.max_period_days}",
            "max_period_days": 1 if dns else self.max_period_days,
            "milestone_percent": 100,
        }

    def _agent(self, project_id: int) -> dict[str, Any] | None:
        row = self._rows.get(project_id)
        return {"status": row["status"], "score": row.get("score")} if row else None

    def search_projects(self, *, query, min_budget, max_budget, skills, limit):
        if not query and not skills:
            raise InvalidInput("give a query or at least one skill")
        terms = query.lower().split()
        wanted = {s.lower() for s in skills}
        results = []
        with self._lock:
            for project in self._projects.values():
                row = self._rows.get(project["id"])
                if row and row["status"] in ENGAGED_STATUSES:
                    continue
                text = f"{project['title']} {project['description']}".lower()
                if terms and not all(t in text for t in terms):
                    continue
                if wanted and not wanted & {s.lower() for s in project["skills"]}:
                    continue
                if min_budget is not None and project["budget"]["max"] < min_budget:
                    continue
                if max_budget is not None and project["budget"]["min"] > max_budget:
                    continue
                summary = {k: project[k] for k in ("id", "title", "url", "type", "budget", "skills")}
                summary.update(
                    bid_count=project["bid_count"],
                    bid_avg=project["bid_avg"],
                    client_country=project["client"]["country_code"],
                    client_payment_verified=project["client"]["payment_verified"],
                    agent=self._agent(project["id"]),
                    agent_rule_filter=None,
                )
                results.append(summary)
        return results[:limit]

    def get_project(self, project_id):
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise NotFound(f"Project {project_id} does not exist.")
            row = self._rows.get(project_id)
            return {
                **project,
                "already_bid": bool(row and row["status"] in ENGAGED_STATUSES),
                "agent": self._agent(project_id),
                "bid_rules": self._bid_rules(project),
            }

    def place_bid(self, *, project_id, amount, period_days, description, dry_run):
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise NotFound(f"Project {project_id} does not exist.")
            row = self._rows.get(project_id)
            if row and row["status"] in ENGAGED_STATUSES:
                raise AlreadyBid(f"Already bid on project {project_id} ({row['amount']} USD). Not bidding again.")
            rules = self._bid_rules(project)
            if period_days > rules["max_period_days"] or (self._is_dns(project) and period_days != 1):
                raise InvalidInput(f"period_days must be {rules['period_days']} for this project")
            if not rules["min_amount"] <= amount <= rules["max_amount"]:
                raise InvalidInput(f"amount must be between {rules['min_amount']} and {rules['max_amount']}")
            bid = {
                "project_id": project_id,
                "title": project["title"],
                "url": project["url"],
                "amount": amount,
                "currency": project["budget"]["currency"],
                "period_days": period_days,
                "milestone_percent": 100,
                "description": description,
            }
            warnings = proposal_style_warnings(description, self.display_name)
            if dry_run:
                return {"dry_run": True, "submitted": False, "would_submit": bid, "style_warnings": warnings}
            bid_id = self._next_bid_id
            self._next_bid_id += 1
            self._rows[project_id] = {
                "status": "bid_submitted",
                "score": None,
                "auto_submitted": 0,
                "bid_id": bid_id,
                "amount": amount,
                "period_days": period_days,
                "submitted_at": int(time.time()),
            }
        return {"dry_run": False, "submitted": True, "bid_id": bid_id, **bid, "style_warnings": warnings}

    def list_my_bids(self, status):
        with self._lock:
            bids = [
                {
                    "bid_id": row["bid_id"],
                    "project_id": pid,
                    "title": self._projects[pid]["title"],
                    "url": self._projects[pid]["url"],
                    "amount": row["amount"],
                    "currency": self._projects[pid]["budget"]["currency"],
                    "period_days": row["period_days"],
                    "status": "active",
                    "submitted_at": row["submitted_at"],
                    "auto_submitted": bool(row["auto_submitted"]),
                }
                for pid, row in self._rows.items()
                if row["status"] == "bid_submitted"
            ]
        if status != "all":
            bids = [b for b in bids if b["status"] == status]
        return sorted(bids, key=lambda b: b["submitted_at"], reverse=True)

    def get_messages(self, *, thread_id, project_id):
        with self._lock:
            if thread_id is not None:
                thread = self._threads.get(thread_id)
            else:
                thread = next((t for t in self._threads.values() if t["project_id"] == project_id), None)
            if thread is None:
                which = f"thread {thread_id}" if thread_id is not None else f"project {project_id}"
                raise NotFound(f"No message thread found for {which}.")
            return {**thread, "messages": list(thread["messages"])}

    def send_message(self, *, thread_id, text, dry_run):
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise NotFound(f"No message thread {thread_id}.")
            if dry_run:
                return {"dry_run": True, "sent": False, "would_send": {"thread_id": thread_id, "text": text}}
            message = {"id": self._next_message_id, "from_me": True, "sender": "me", "text": text,
                       "sent_at": int(time.time())}  # fmt: skip
            self._next_message_id += 1
            thread["messages"].append(message)
        return {"dry_run": False, "sent": True, "thread_id": thread_id, "message": message}
