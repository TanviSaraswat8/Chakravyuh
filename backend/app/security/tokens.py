"""Cookie-based sign-in sessions.

The cookie carries a 256-bit random token (HttpOnly, SameSite, Secure outside local development).
The database stores only SHA-256(token). The CSRF token is derived from the session token, returned in
the JSON body of /auth/login and /auth/me, kept in page memory by the frontend, and must be echoed in
X-CSRF-Token on every state-changing request. Nothing is ever written to localStorage.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuthSession, User

COOKIE = "chakravyuh_session"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes even for timezone=True columns; treat them as UTC."""
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def csrf_for(token: str) -> str:
    return _sha("csrf:" + token)


def csrf_ok(token: str, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(csrf_for(token), supplied)


def create(db: Session, user: User) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    t = now()
    s = AuthSession(user_id=user.id, token_hash=_sha(token), created_at=t, last_seen_at=t,
                    expires_at=t + timedelta(minutes=settings.session_ttl_minutes))
    # reauth_at stays empty: signing in does not count as the step-up for high-risk actions.
    db.add(s)
    db.commit()
    return token, s


def resolve(db: Session, token: str | None) -> tuple[User, AuthSession] | None:
    if not token or len(token) > 128:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == _sha(token)))
    if s is None or s.revoked_at is not None:
        return None
    t = now()
    if aware(s.expires_at) <= t or aware(s.last_seen_at) <= t - timedelta(minutes=settings.session_idle_minutes):
        return None
    user = db.get(User, s.user_id)
    if user is None or user.status != "active":
        return None
    if aware(s.last_seen_at) <= t - timedelta(seconds=60):     # sliding idle timeout, at most one write/min
        s.last_seen_at = t
        db.commit()
    return user, s


def revoke(db: Session, s: AuthSession) -> None:
    s.revoked_at = now()
    db.commit()


def revoke_all(db: Session, user_id: str) -> None:
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id,
                                                  AuthSession.revoked_at.is_(None))):
        s.revoked_at = now()
    db.commit()


def fresh_reauth(s: AuthSession) -> bool:
    r = aware(s.reauth_at)
    return r is not None and r >= now() - timedelta(seconds=settings.reauth_window_seconds)


def set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=settings.session_ttl_minutes * 60, httponly=True,
                    secure=settings.cookie_secure, samesite=settings.cookie_samesite, path="/")


def clear_cookie(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/", httponly=True, secure=settings.cookie_secure,
                       samesite=settings.cookie_samesite)
