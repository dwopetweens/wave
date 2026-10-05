"""Client-side throttle in front of the Freelancer API.

Freelancer.com rate-limits per token, and the poller and portal share that token,
so the MCP server keeps its own budget of API calls and backs off entirely after the
API answers 429. Thread-safe: backend calls run in worker threads.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from freelancer_mcp.backend import RateLimited


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: float, max_wait_seconds: float = 5.0):
        self.max_calls = max_calls
        self.period = period_seconds
        self.max_wait = max_wait_seconds
        self._calls: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def back_off(self, seconds: float | None = None) -> None:
        """Called when the API itself answered 429."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + (seconds or self.period))

    def acquire(self) -> None:
        """Take one API call from the budget, waiting briefly if it is nearly free."""
        with self._lock:
            now = time.monotonic()
            if now < self._blocked_until:
                wait = self._blocked_until - now
                raise RateLimited(
                    f"Freelancer API is rate-limiting this account. Try again in {wait:.0f} seconds.",
                    retry_after=wait,
                )
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                wait = self.period - (now - self._calls[0])
                if wait > self.max_wait:
                    raise RateLimited(
                        f"This server's limit of {self.max_calls} Freelancer API calls per "
                        f"{self.period:.0f}s is used up. Try again in {wait:.0f} seconds.",
                        retry_after=wait,
                    )
                time.sleep(wait)
                self._calls.popleft()
            self._calls.append(time.monotonic())
