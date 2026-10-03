"""In-process sliding-window rate limits and a single-flight guard for expensive model operations.

State lives in the API process, which runs as a single Uvicorn worker in every deployment config here.
With several workers or replicas each keeps its own counters, so limits become per-process; a shared
store (Redis) is the upgrade path.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from ..config import settings

# name: (max requests, window seconds). Documented in docs/SECURITY_REMEDIATION.md.
LIMITS: dict[str, tuple[int, int]] = {
    "auth_register_ip": (5, 3600),
    "auth_login_ip": (10, 300),
    "auth_login_email": (5, 300),
    "auth_reauth_user": (5, 300),
    "session_create_user": (30, 60),
    "session_event_user": (120, 60),
    "score_ip": (60, 60),
    "scenario_ip": (60, 60),
    "simulate_ip": (10, 60),
    "arena_ip": (6, 600),
    "adapt_user": (3, 600),
    "campaign_refresh_user": (6, 600),
    "admin_user": (30, 600),
    "beta_signup_ip": (5, 3600),
    "beta_feedback_ip": (20, 600),
}


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> float | None:
        """Count one request. Return seconds to wait if over the limit, else None."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, q[0] + window - now)
            q.append(now)
            if len(self._hits) > 50_000:          # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - 3600]:
                    del self._hits[k]
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if settings.trust_forwarded_for:
        xff = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            return hops[-1][:64]      # the address our own proxy saw; earlier hops are client-supplied
    return (request.client.host if request.client else "unknown")[:64]


def enforce(name: str, subject: str) -> None:
    if not settings.rate_limits_enabled:
        return
    limit, window = LIMITS[name]
    wait = limiter.hit(f"{name}:{subject}", limit, window)
    if wait is not None:
        raise HTTPException(429, "Too many requests. Try again later.",
                            headers={"Retry-After": str(int(wait) + 1)})


def by_ip(name: str):
    """FastAPI dependency: limit `name` per client IP."""
    def dep(request: Request) -> None:
        enforce(name, client_ip(request))
    return dep


class SingleFlight:
    """At most one expensive model operation (arena run or defender update) at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            raise HTTPException(429, "Another model operation is running. Try again shortly.",
                                headers={"Retry-After": "10"})
        return self

    def __exit__(self, *exc) -> None:
        self._lock.release()


model_ops = SingleFlight()
