"""Live scoring: create a session, stream events into it, get decisions and alerts back.

Every stored session belongs to the user who created it. Reading or changing someone else's session
gets the same 404 as a session that doesn't exist, so IDs can't be probed; the attempt is audited.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, require_permission
from ..models import Alert, Event, ScamSession
from ..schemas import AlertOut, AlertResponse, EventIn, ScoreOut, ScoreRequest, SessionCreate, SessionOut, StepOut
from ..security import audit, ratelimit
from ..services.scoring import score_session

router = APIRouter(prefix="/v1", tags=["sessions"])


def _event_dict(e: Event) -> dict:
    return {"t": e.t, "type": e.type, "text": e.text, "channel": e.channel, "attrs": e.attrs or {},
            "stage": "contact", "tactics": e.tactics or [],
            "client_tags": (e.attrs or {}).get("_client_tags")}


def _owned(db: Session, sid: str, p: Principal, request: Request) -> ScamSession:
    s = db.get(ScamSession, sid)
    if s is not None and s.owner_id == p.id:
        return s
    if s is not None:          # exists but belongs to someone else: log it, answer as if it didn't exist
        audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                     resource_type="session", resource_id=sid, reason="not owner")
    raise HTTPException(404, "Session not found")


def _alert_out(a: Alert) -> AlertOut:
    return AlertOut(id=a.id, level=a.level, action=a.action, reason_code=a.reason_code, title=a.title,
                    message=a.message, p=a.p, response=a.response, created_at=a.created_at)


@router.post("/score", response_model=ScoreOut, dependencies=[Depends(ratelimit.by_ip("score_ip"))])
def score_stateless(req: ScoreRequest) -> ScoreOut:
    """Score a whole event list at once (no storage). Used by the demo replay and integrations."""
    events = []
    for i, e in enumerate(req.events):
        d = e.model_dump()
        d["t"] = d["t"] if d["t"] is not None else float(i * 60)
        d["stage"] = "contact"
        d["tactics"] = []
        if e.client_tags:
            d["client_tags"] = e.client_tags.model_dump()
        events.append(d)
    out = score_session(events, req.language, req.channel)
    return ScoreOut(mode=out["mode"], latest=StepOut(**out["latest"]),
                    steps=[StepOut(**s) for s in out["steps"]],
                    alert=AlertOut(**out["alert"]) if out["alert"] else None, family_guess=out["family_guess"])


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, request: Request, db: Session = Depends(get_db),
                   p: Principal = Depends(require_permission("sessions:write"))) -> SessionOut:
    ratelimit.enforce("session_create_user", p.id)
    s = ScamSession(channel=body.channel, language=body.language, source=body.source, owner_id=p.id)
    db.add(s)
    db.commit()
    audit.record("SESSION_CREATE", request=request, actor=p.user, resource_type="session", resource_id=s.id)
    return _session_out(s)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(request: Request, limit: int = 50, min_level: int = 0, db: Session = Depends(get_db),
                  p: Principal = Depends(require_permission("sessions:read"))) -> list[SessionOut]:
    rows = db.scalars(select(ScamSession).where(ScamSession.owner_id == p.id,
                                                ScamSession.current_level >= min_level)
                      .order_by(ScamSession.updated_at.desc()).limit(min(limit, 200))).all()
    return [SessionOut(id=s.id, source=s.source, channel=s.channel, language=s.language, status=s.status,
                       current_level=s.current_level, max_p=s.max_p, family_guess=s.family_guess,
                       outcome=s.outcome, created_at=s.created_at,
                       alerts=[_alert_out(a) for a in s.alerts]) for s in rows]


@router.get("/sessions/{sid}", response_model=SessionOut)
def get_session(sid: str, request: Request, db: Session = Depends(get_db),
                p: Principal = Depends(require_permission("sessions:read"))) -> SessionOut:
    s = _owned(db, sid, p, request)
    audit.record("SESSION_ACCESS", request=request, actor=p.user, resource_type="session", resource_id=sid)
    return _session_out(s)


def _session_out(s: ScamSession) -> SessionOut:
    return SessionOut(
        id=s.id, source=s.source, channel=s.channel, language=s.language, status=s.status,
        current_level=s.current_level, max_p=s.max_p, family_guess=s.family_guess, outcome=s.outcome,
        created_at=s.created_at,
        events=[{"idx": e.idx, "t": e.t, "type": e.type, "text": e.text, "tactics": e.tactics or [],
                 "attrs": {k: v for k, v in (e.attrs or {}).items() if not k.startswith("_")},
                 "p": e.p, "level": e.level, "next_stage": e.next_stage} for e in s.events],
        alerts=[_alert_out(a) for a in s.alerts])


@router.post("/sessions/{sid}/events", response_model=ScoreOut)
def add_event(sid: str, ev: EventIn, request: Request, db: Session = Depends(get_db),
              p: Principal = Depends(require_permission("sessions:write"))) -> ScoreOut:
    ratelimit.enforce("session_event_user", p.id)
    s = _owned(db, sid, p, request)
    if s.status != "open":
        raise HTTPException(409, "Session is closed")
    t = ev.t
    if t is None:
        t = (datetime.now(UTC) - s.created_at.replace(tzinfo=UTC)).total_seconds()
    attrs = dict(ev.attrs)
    if ev.client_tags:
        attrs["_client_tags"] = ev.client_tags.model_dump()
    row = Event(session_id=s.id, idx=len(s.events), t=float(t), type=ev.type, channel=ev.channel or s.channel,
                text=ev.text if (settings.store_message_text or ev.type != "MSG_RECV") else None, attrs=attrs)
    s.events.append(row)
    db.flush()

    history = [_event_dict(e) for e in s.events]
    if not settings.store_message_text and ev.text:
        history[-1]["text"] = ev.text        # scored in memory, never stored
    out = score_session(history, s.language, s.channel)

    for e, step in zip(s.events, out["steps"]):
        e.p, e.level = step["p"], step["level"]
        e.next_stage, e.tactics = step.get("next_stage"), step.get("tactics", [])
    if not settings.store_message_text and ev.type == "MSG_RECV" and ev.text and not ev.client_tags:
        # Keep what the text told us (tactics, message risk) so later events can still use it,
        # exactly like on-device mode. The text itself is never written to the database.
        last = out["steps"][-1]
        row.attrs = {**row.attrs, "_client_tags": {"tactics": last.get("tactics", []),
                                                   "p_scam": last.get("msg_p", 0.0),
                                                   "stage": last.get("stage_guess")}}
    latest = out["latest"]
    s.max_p = max(s.max_p, latest["p"])
    s.current_level = max(s.current_level, latest["level"])
    s.family_guess = out["family_guess"] or s.family_guess
    s.embedding = out["embedding"]
    if ev.type == "PAY" and not attrs.get("cancelled"):
        s.outcome = s.outcome or "paid"
    alert_out = None
    if out["alert"]:
        a = Alert(session_id=s.id, event_idx=row.idx, language=s.language, **out["alert"])
        db.add(a)
        db.flush()
        alert_out = _alert_out(a)
    db.commit()
    audit.record("SESSION_MUTATION", request=request, actor=p.user, resource_type="session", resource_id=s.id,
                 detail={"op": "add_event", "event_type": ev.type, "level": latest["level"]})
    return ScoreOut(session_id=s.id, mode=out["mode"], latest=StepOut(**latest),
                    steps=[StepOut(**st) for st in out["steps"]], alert=alert_out, family_guess=out["family_guess"])


@router.post("/sessions/{sid}/close", response_model=SessionOut)
def close_session(sid: str, request: Request, db: Session = Depends(get_db),
                  p: Principal = Depends(require_permission("sessions:write"))) -> SessionOut:
    s = _owned(db, sid, p, request)
    s.status = "closed"
    db.commit()
    audit.record("SESSION_MUTATION", request=request, actor=p.user, resource_type="session", resource_id=sid,
                 detail={"op": "close"})
    return _session_out(s)


@router.post("/alerts/{aid}/respond", response_model=AlertOut)
def respond(aid: str, body: AlertResponse, request: Request, db: Session = Depends(get_db),
            p: Principal = Depends(require_permission("sessions:write"))) -> AlertOut:
    """User's answer to an alert. 'legit' suppresses future alerts for this payee (habituation control)."""
    a = db.get(Alert, aid)
    if a is None or a.session.owner_id != p.id:
        if a is not None:
            audit.record("AUTHORIZATION_DENIED", "denied", request=request, actor=p.user,
                         resource_type="alert", resource_id=aid, reason="not owner")
        raise HTTPException(404, "Alert not found")
    a.response = body.response
    a.responded_at = datetime.now(UTC)
    s = a.session
    if body.response == "cancelled":
        s.outcome = "cancelled"
    elif body.response == "legit":
        s.outcome = "legit"
    db.commit()
    audit.record("SESSION_MUTATION", request=request, actor=p.user, resource_type="alert", resource_id=aid,
                 detail={"op": "respond", "response": body.response})
    return _alert_out(a)
