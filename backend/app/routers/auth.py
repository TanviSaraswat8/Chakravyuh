"""Sign-up, sign-in, sign-out, current user, and step-up re-authentication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, optional_user, require_user
from ..models import User
from ..schemas import LoginIn, ReauthIn, RegisterIn
from ..security import audit, passwords, ratelimit, rbac, tokens
from ..services.users import UserError, create_user, normalise_email

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _me(user: User, token: str) -> dict:
    return {"user": {"id": user.id, "email": user.email, "role": user.role, "status": user.status,
                     "permissions": rbac.permissions_of(user.role)},
            "csrf_token": tokens.csrf_for(token)}


@router.post("/register", status_code=201, dependencies=[Depends(ratelimit.by_ip("auth_register_ip"))])
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Self sign-up. New accounts are ANALYSTs: they can run and see only their own sessions."""
    if not settings.allow_registration:
        raise HTTPException(403, "Sign-up is closed")
    try:
        u = create_user(db, body.email, body.password, rbac.Role.ANALYST)
    except UserError as e:
        raise HTTPException(400 if "already exists" not in str(e) else 409, str(e)) from None
    audit.record("REGISTER", request=request, actor=u, resource_type="user", resource_id=u.id)
    return {"id": u.id, "email": u.email, "role": u.role}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    email = normalise_email(body.email)
    ratelimit.enforce("auth_login_ip", ratelimit.client_ip(request))
    ratelimit.enforce("auth_login_email", email)
    user = db.scalar(select(User).where(User.email == email))
    ok = passwords.verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None or user.status != "active":
        audit.record("FAILED_LOGIN", "failure", request=request, actor=user, resource_type="user",
                     resource_id=user.id if user else None,
                     reason="bad credentials" if not ok or user is None else "account disabled")
        raise HTTPException(401, "Invalid email or password")
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(body.password)
        db.commit()
    token, _ = tokens.create(db, user)
    tokens.set_cookie(response, token)
    audit.record("LOGIN", request=request, actor=user, resource_type="user", resource_id=user.id)
    return _me(user, token)


@router.post("/logout")
def logout(request: Request, response: Response, p: Principal = Depends(require_user),
           db: Session = Depends(get_db)) -> dict:
    tokens.revoke(db, db.merge(p.auth))
    tokens.clear_cookie(response)
    audit.record("LOGOUT", request=request, actor=p.user, resource_type="user", resource_id=p.id)
    return {"signed_out": True}


@router.get("/me")
def me(p: Principal | None = Depends(optional_user)) -> dict:
    if p is None:
        raise HTTPException(401, "Not signed in")
    return _me(p.user, p.token)


@router.post("/reauth")
def reauth(body: ReauthIn, request: Request, p: Principal = Depends(require_user),
           db: Session = Depends(get_db)) -> dict:
    """Confirm the password again before a high-risk action (persisting a model, changing roles)."""
    ratelimit.enforce("auth_reauth_user", p.id)
    if not passwords.verify_password(p.user.password_hash, body.password):
        audit.record("FAILED_REAUTH", "failure", request=request, actor=p.user, resource_type="user",
                     resource_id=p.id)
        raise HTTPException(401, "Password incorrect")
    s = db.merge(p.auth)
    s.reauth_at = tokens.now()
    db.commit()
    audit.record("REAUTH", request=request, actor=p.user, resource_type="user", resource_id=p.id)
    return {"reauthenticated": True, "valid_seconds": settings.reauth_window_seconds}
