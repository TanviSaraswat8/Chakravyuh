"""Security audit log, written to the audit_events table in its own transaction.

Records are written even when the request itself fails (denials raise right after logging). Details are
filtered so that passwords, tokens, keys, cookies and message text can never be stored, whatever a
caller passes in.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import Request

log = logging.getLogger("chakravyuh.audit")

ACTIONS = {
    "LOGIN", "FAILED_LOGIN", "LOGOUT", "REGISTER", "REAUTH", "FAILED_REAUTH",
    "SESSION_CREATE", "SESSION_ACCESS", "SESSION_MUTATION",
    "MODEL_ADAPT", "MODEL_PERSIST", "MODEL_LOAD_FAILURE",
    "AUTHORIZATION_DENIED", "ADMIN_ACTION", "ROLE_CHANGE", "CAMPAIGN_CHANGE",
}

_SECRET_KEY = re.compile(r"pass|token|secret|key|cookie|auth|csrf|text|message|comment|credential", re.I)


def _clean(detail: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (detail or {}).items():
        if _SECRET_KEY.search(k):
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:120]
    return out


def record(action: str, result: str = "success", *, request: Request | None = None, actor: Any = None,
           resource_type: str | None = None, resource_id: str | None = None, reason: str | None = None,
           detail: dict[str, Any] | None = None) -> None:
    from ..db import SessionLocal
    from ..models import AuditEvent
    from .ratelimit import client_ip

    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action}")
    ev = AuditEvent(
        action=action, result=result,
        request_id=getattr(request.state, "request_id", None) if request is not None else None,
        actor_id=getattr(actor, "id", None), actor_role=getattr(actor, "role", None),
        resource_type=resource_type, resource_id=(resource_id or None) and str(resource_id)[:64],
        reason=reason[:200] if reason else None,
        source_ip=client_ip(request) if request is not None else None,
        detail=_clean(detail),
    )
    try:
        with SessionLocal() as db:
            db.add(ev)
            db.commit()
    except Exception:                       # the audit trail must never take the API down with it
        log.exception("could not write audit event %s", action)
    log.info("audit %s %s actor=%s %s:%s", action, result, ev.actor_id, resource_type, ev.resource_id)
