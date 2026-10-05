"""The interface the MCP tools call, and the errors they turn into tool messages.

`AgentBackend` (to be added in `agent_backend.py`) adapts the existing bidding agent's
Freelancer client and SQLite module to this interface. `FakeBackend` serves sample
data so every tool can be exercised in the MCP Inspector without touching the live
account.

Backend methods are synchronous because they wrap the agent's existing code; the
server runs them in a worker thread.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

BidStatus = Literal["active", "awarded", "rejected", "all"]


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
        """Active projects, excluding any already bid on according to the agent's SQLite."""
        ...

    def get_project(self, project_id: int) -> dict[str, Any]: ...

    def place_bid(
        self, *, project_id: int, amount: float, period_days: int, description: str, dry_run: bool
    ) -> dict[str, Any]:
        """Submit a bid and log it to the agent's bids table.

        Must refuse with `AlreadyBid` when the project is already bid on, checked and
        recorded under the same write lock the agent uses, so the two never double-bid.
        With `dry_run`, run every check and return what would be sent, without
        submitting or logging anything.
        """
        ...

    def list_my_bids(self, status: BidStatus) -> list[dict[str, Any]]: ...

    def get_messages(self, *, thread_id: int | None, project_id: int | None) -> dict[str, Any]: ...

    def send_message(self, *, thread_id: int, text: str, dry_run: bool) -> dict[str, Any]: ...


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class FakeBackend:
    """In-memory sample data with the same shapes and rules as the real backend."""

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._lock = threading.Lock()
        self._projects: dict[int, dict[str, Any]] = {
            40000001: {
                "id": 40000001,
                "title": "Build a Telegram bot that posts daily sales reports",
                "url": "https://www.freelancer.com/projects/python/telegram-bot-sales-reports",
                "type": "fixed",
                "budget": {"min": 250.0, "max": 750.0, "currency": "USD"},
                "skills": ["Python", "Telegram API", "SQLite"],
                "bid_count": 14,
                "bid_avg": 480.0,
                "submitted_at": _iso(now - timedelta(hours=3)),
                "description": "We need a bot that reads our Postgres sales table every morning "
                "and posts a summary chart to a Telegram group.",
                "client": {
                    "id": 9001,
                    "username": "acme_retail",
                    "country": "United Kingdom",
                    "rating": 4.9,
                    "reviews": 37,
                    "payment_verified": True,
                    "hire_rate": 0.82,
                    "projects_posted": 45,
                },
            },
            40000002: {
                "id": 40000002,
                "title": "Scrape product prices from three e-commerce sites",
                "url": "https://www.freelancer.com/projects/web-scraping/scrape-product-prices",
                "type": "hourly",
                "budget": {"min": 15.0, "max": 25.0, "currency": "USD"},
                "skills": ["Python", "Web Scraping", "Playwright"],
                "bid_count": 41,
                "bid_avg": 19.5,
                "submitted_at": _iso(now - timedelta(minutes=40)),
                "description": "Daily price scrape into a Google Sheet. Sites use heavy JavaScript.",
                "client": {
                    "id": 9002,
                    "username": "pricewatch_ke",
                    "country": "Kenya",
                    "rating": None,
                    "reviews": 0,
                    "payment_verified": False,
                    "hire_rate": None,
                    "projects_posted": 1,
                },
            },
            40000003: {
                "id": 40000003,
                "title": "FastAPI backend for a booking app",
                "url": "https://www.freelancer.com/projects/fastapi/booking-app-backend",
                "type": "fixed",
                "budget": {"min": 1500.0, "max": 3000.0, "currency": "USD"},
                "skills": ["Python", "FastAPI", "PostgreSQL"],
                "bid_count": 22,
                "bid_avg": 2100.0,
                "submitted_at": _iso(now - timedelta(days=1)),
                "description": "REST API with auth, availability calendar and Stripe payments.",
                "client": {
                    "id": 9003,
                    "username": "bookly_io",
                    "country": "Germany",
                    "rating": 4.6,
                    "reviews": 12,
                    "payment_verified": True,
                    "hire_rate": 0.67,
                    "projects_posted": 18,
                },
            },
        }
        # Stands in for the agent's bids table.
        self._bids: dict[int, dict[str, Any]] = {
            40000003: {
                "bid_id": 70000001,
                "project_id": 40000003,
                "project_title": "FastAPI backend for a booking app",
                "amount": 2200.0,
                "period_days": 21,
                "status": "active",
                "submitted_at": _iso(now - timedelta(hours=20)),
                "source": "agent",
            }
        }
        self._threads: dict[int, dict[str, Any]] = {
            80000001: {
                "thread_id": 80000001,
                "project_id": 40000003,
                "messages": [
                    {
                        "id": 1,
                        "from": "bookly_io",
                        "is_me": False,
                        "text": "Hi, can you start next week?",
                        "sent_at": _iso(now - timedelta(hours=2)),
                    }
                ],
            }
        }
        self._next_bid_id = 70000002
        self._next_message_id = 2

    @staticmethod
    def _summary(project: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "title", "url", "type", "budget", "skills", "bid_count", "bid_avg", "submitted_at")
        summary = {k: project[k] for k in keys}
        summary["client_country"] = project["client"]["country"]
        return summary

    def search_projects(self, *, query, min_budget, max_budget, skills, limit):
        terms = query.lower().split()
        wanted_skills = {s.lower() for s in skills}
        results = []
        with self._lock:
            for project in self._projects.values():
                if project["id"] in self._bids:
                    continue
                text = f"{project['title']} {project['description']}".lower()
                if terms and not all(t in text for t in terms):
                    continue
                if wanted_skills and not wanted_skills & {s.lower() for s in project["skills"]}:
                    continue
                if min_budget is not None and project["budget"]["max"] < min_budget:
                    continue
                if max_budget is not None and project["budget"]["min"] > max_budget:
                    continue
                results.append(self._summary(project))
        return results[:limit]

    def get_project(self, project_id):
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise NotFound(f"Project {project_id} does not exist or is no longer active.")
            detail = dict(project)
            detail["already_bid"] = project_id in self._bids
        return detail

    def place_bid(self, *, project_id, amount, period_days, description, dry_run):
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise NotFound(f"Project {project_id} does not exist or is no longer active.")
            if project_id in self._bids:
                existing = self._bids[project_id]
                raise AlreadyBid(
                    f"Already bid on project {project_id} ({existing['amount']} "
                    f"{project['budget']['currency']}, by {existing['source']}). Not bidding again."
                )
            bid = {
                "project_id": project_id,
                "project_title": project["title"],
                "amount": amount,
                "currency": project["budget"]["currency"],
                "period_days": period_days,
                "description": description,
            }
            if dry_run:
                return {"dry_run": True, "submitted": False, "would_submit": bid}
            record = {
                "bid_id": self._next_bid_id,
                "project_id": project_id,
                "project_title": project["title"],
                "amount": amount,
                "period_days": period_days,
                "status": "active",
                "submitted_at": _iso(datetime.now(timezone.utc)),
                "source": "mcp",
            }
            self._next_bid_id += 1
            self._bids[project_id] = record
        return {"dry_run": False, "submitted": True, "bid": record}

    def list_my_bids(self, status):
        with self._lock:
            bids = list(self._bids.values())
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
            message = {
                "id": self._next_message_id,
                "from": "me",
                "is_me": True,
                "text": text,
                "sent_at": _iso(datetime.now(timezone.utc)),
            }
            self._next_message_id += 1
            thread["messages"].append(message)
        return {"dry_run": False, "sent": True, "thread_id": thread_id, "message": message}
