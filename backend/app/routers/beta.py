"""Alpha / beta testing: sign-up (issues an API key) and feedback collection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_tester, require_admin
from ..models import BetaTester, Feedback
from ..schemas import BetaSignup, FeedbackIn

router = APIRouter(prefix="/v1/beta", tags=["beta"])


@router.post("/signup", status_code=201)
def signup(body: BetaSignup, db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(BetaTester).where(BetaTester.email == body.email.lower())):
        raise HTTPException(409, "This email is already registered")
    t = BetaTester(email=body.email.lower(), name=body.name, org=body.org, role=body.role)
    db.add(t)
    db.commit()
    return {"id": t.id, "api_key": t.api_key, "cohort": t.cohort,
            "note": "Keep this key private. Send it as the X-API-Key header."}


@router.post("/feedback", status_code=201)
def feedback(body: FeedbackIn, db: Session = Depends(get_db),
             tester: BetaTester | None = Depends(current_tester)) -> dict:
    f = Feedback(tester_id=tester.id if tester else None, **body.model_dump())
    db.add(f)
    db.commit()
    return {"id": f.id, "thanks": True}


@router.get("/feedback", dependencies=[Depends(require_admin)])
def list_feedback(limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Feedback).order_by(Feedback.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": f.id, "kind": f.kind, "rating": f.rating, "comment": f.comment, "page": f.page,
             "session_id": f.session_id, "alert_id": f.alert_id, "tester_id": f.tester_id,
             "created_at": f.created_at} for f in rows]


@router.get("/testers", dependencies=[Depends(require_admin)])
def list_testers(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(BetaTester).order_by(BetaTester.created_at.desc())).all()
    return [{"id": t.id, "email": t.email, "name": t.name, "org": t.org, "role": t.role, "cohort": t.cohort,
             "created_at": t.created_at} for t in rows]
