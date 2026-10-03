"""Request dependencies: who is calling, and are they allowed to do this.

Every protected route resolves the caller from the session cookie on the server and checks a permission
from app/security/rbac.py. The frontend never decides access.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, BetaTester, User
from .security import audit, rbac, tokens

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Principal:
    user: User
    auth: AuthSession
    token: str

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role


def optional_user(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    token = request.cookies.get(tokens.COOKIE)
    found = tokens.resolve(db, token)
    if found is None:
        return None
    user, s = found
    return Principal(user, s, token)


def require_user(request: Request, p: Principal | None = Depends(optional_user)) -> Principal:
    if p is None:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Cookie"})
    if request.method in UNSAFE and not tokens.csrf_ok(p.token, request.headers.get("x-csrf-token")):
        audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                     resource_type="route", resource_id=request.url.path, reason="missing or invalid CSRF token")
        raise HTTPException(403, "Missing or invalid CSRF token")
    return p


def require_permission(permission: str):
    if permission not in rbac.PERMISSIONS:
        raise ValueError(f"unknown permission {permission}")

    def dep(request: Request, p: Principal = Depends(require_user)) -> Principal:
        if not rbac.allowed(p.role, permission):
            audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                         resource_type="permission", resource_id=permission, reason=f"role {p.role}")
            raise HTTPException(403, "You don't have permission to do this")
        if permission in rbac.STEP_UP and not tokens.fresh_reauth(p.auth):
            audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                         resource_type="permission", resource_id=permission, reason="step-up required")
            raise HTTPException(403, "Re-enter your password to confirm this action (POST /v1/auth/reauth)",
                                headers={"X-Step-Up-Required": "true"})
        return p
    return dep


def step_up(request: Request, p: Principal, permission: str) -> None:
    """For routes where a high-risk option (e.g. persist=true) is chosen per request."""
    if not rbac.allowed(p.role, permission):
        audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                     resource_type="permission", resource_id=permission, reason=f"role {p.role}")
        raise HTTPException(403, "You don't have permission to do this")
    if not tokens.fresh_reauth(p.auth):
        audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                     resource_type="permission", resource_id=permission, reason="step-up required")
        raise HTTPException(403, "Re-enter your password to confirm this action (POST /v1/auth/reauth)",
                            headers={"X-Step-Up-Required": "true"})


# --- Transitional beta tester keys -----------------------------------------------------------------
# Tester keys predate accounts. They are now accepted ONLY to attribute beta feedback; they grant no
# access to sessions, models or admin data. Only SHA-256(key) is stored. Remove once the beta ends.

def hash_tester_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def current_tester(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> BetaTester | None:
    if not x_api_key:
        return None
    tester = db.scalar(select(BetaTester).where(BetaTester.api_key_hash == hash_tester_key(x_api_key)))
    if tester is None:
        raise HTTPException(401, "Invalid tester key")
    return tester
