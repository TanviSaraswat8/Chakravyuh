"""Administration: users and roles, and the security audit log. ADMIN only, enforced server-side."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, require_permission
from ..models import AuditEvent, User
from ..schemas import UserPatch
from ..security import audit, ratelimit, tokens

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/users")
def list_users(p: Principal = Depends(require_permission("users:manage")),
               db: Session = Depends(get_db)) -> list[dict]:
    ratelimit.enforce("admin_user", p.id)
    rows = db.scalars(select(User).order_by(User.created_at.desc()).limit(500)).all()
    return [{"id": u.id, "email": u.email, "role": u.role, "status": u.status, "created_at": u.created_at}
            for u in rows]


@router.patch("/users/{uid}")
def patch_user(uid: str, body: UserPatch, request: Request,
               p: Principal = Depends(require_permission("users:manage")), db: Session = Depends(get_db)) -> dict:
    ratelimit.enforce("admin_user", p.id)
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == p.id:
        raise HTTPException(400, "Admins cannot change their own role or status")
    before = {"role": u.role, "status": u.status}
    if body.role is not None:
        u.role = body.role
    if body.status is not None:
        u.status = body.status
    db.commit()
    if body.status == "disabled" or (body.role is not None and body.role != before["role"]):
        tokens.revoke_all(db, u.id)        # new privileges take effect on next sign-in
    audit.record("ROLE_CHANGE" if body.role is not None else "ADMIN_ACTION", request=request, actor=p.user,
                 resource_type="user", resource_id=u.id,
                 detail={"from_role": before["role"], "to_role": u.role,
                         "from_status": before["status"], "to_status": u.status})
    return {"id": u.id, "email": u.email, "role": u.role, "status": u.status}


@router.get("/audit")
def list_audit(request: Request, limit: int = Query(100, ge=1, le=500), action: str | None = None,
               p: Principal = Depends(require_permission("audit:read")), db: Session = Depends(get_db)) -> list[dict]:
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if action:
        q = q.where(AuditEvent.action == action)
    rows = db.scalars(q).all()
    audit.record("ADMIN_ACTION", request=request, actor=p.user, resource_type="audit_log",
                 detail={"op": "read", "n": len(rows)})
    return [{"id": e.id, "at": e.created_at, "request_id": e.request_id, "action": e.action, "result": e.result,
             "actor_id": e.actor_id, "actor_role": e.actor_role, "resource_type": e.resource_type,
             "resource_id": e.resource_id, "reason": e.reason, "source_ip": e.source_ip, "detail": e.detail}
            for e in rows]
