"""Analyst-facing intelligence: payee risk, emerging campaigns, metrics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, require_permission
from ..models import Alert, BetaTester, Campaign, Feedback, ScamSession
from ..schemas import CampaignPatch
from ..security import audit, ratelimit
from ..services.demo import simulate
from ..services.scoring import get_engine, model_status

router = APIRouter(prefix="/v1", tags=["intel"])


@router.get("/meta")
def meta() -> dict:
    report = {}
    p = Path(settings.artifacts_dir) / "metrics.json"
    if p.exists():
        report = json.loads(p.read_text())
    return {"model": model_status(), "benchmark": report}


@router.get("/payees/{vpa}/risk")
def payee_risk(vpa: str) -> dict:
    eng = get_engine()
    if eng is None:
        return {"vpa": vpa, "risk": None, "known": False}
    known = vpa in eng.payee_scores
    return {"vpa": vpa, "risk": eng.payee_risk(vpa), "known": known}


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Campaign).order_by(Campaign.created_at.desc())).all()
    return [{"id": c.id, "name": c.name, "size": c.size, "status": c.status, "card": c.card,
             "created_at": c.created_at} for c in rows]


@router.post("/campaigns/refresh")
def refresh_campaigns(request: Request, include_simulated: bool = True, db: Session = Depends(get_db),
                      who: Principal = Depends(require_permission("campaigns:manage"))) -> dict:
    """Cluster risky sessions that match no known scam family into campaign cards.

    Users' stored sessions contribute to clustering, but campaign cards are readable by anyone, so their
    message text and payee IDs are removed before cards are built: a card can never quote another
    user's conversation."""
    ratelimit.enforce("campaign_refresh_user", who.id)
    eng = get_engine()
    if eng is None or eng.campaigns is None:
        raise HTTPException(503, "Model not loaded")
    pool: list[dict] = []
    if include_simulated:
        # Inject a fresh batch of never-trained scams so the demo always has something emerging.
        pool += simulate(60, ["echallan_link"], 1.0, seed=99)
        pool += simulate(60, None, 0.0, seed=98)
    stored = db.scalars(select(ScamSession).where(ScamSession.max_p > 0.3)).all()
    for s in stored:
        pool.append({"_stored": True, "session_id": s.id, "language": s.language, "channel": s.channel, "label": 0,
                     "events": [{"t": e.t, "type": e.type, "text": e.text, "attrs": e.attrs or {},
                                 "tactics": e.tactics or [], "stage": "contact", "channel": e.channel}
                                for e in s.events]})
    if not pool:
        return {"created": 0}
    res = eng.decide(pool)
    emb = np.stack([r["embedding"] for r in res])
    p = np.array([max(d["p"] for d in r["decisions"]) if r["decisions"] else 0.0 for r in res])
    unknown = eng.campaigns.is_unknown(emb, p)
    members = [s for s, u in zip(pool, unknown) if u]
    for s, r in zip(pool, res):     # tactics predicted by the tagger, for the card
        for e in s["events"]:
            if e.get("text") in r["tags"]:
                e["tags"] = r["tags"][e["text"]]["tactics"]
        if s.get("_stored"):
            for e in s["events"]:
                e["text"] = None
                e["attrs"] = {k: v for k, v in e["attrs"].items() if k != "payee" and not k.startswith("_")}
    cards = eng.campaigns.cluster(members, emb[unknown]) if members else []
    psi = eng.campaigns.psi([[t for e in s["events"] for t in e.get("tags", [])] for s in pool])
    created = 0
    for c in cards:
        db.add(Campaign(name=c["name"], size=c["size"], card=c))
        created += 1
    db.commit()
    audit.record("CAMPAIGN_CHANGE", request=request, actor=who.user, resource_type="campaigns",
                 detail={"op": "refresh", "created": created})
    return {"created": created, "unknown_sessions": int(unknown.sum()), "pool": len(pool),
            "tactic_drift_psi": round(psi, 4), "drift_alarm": psi > 0.2}


@router.patch("/campaigns/{cid}")
def patch_campaign(cid: str, body: CampaignPatch, request: Request, db: Session = Depends(get_db),
                   who: Principal = Depends(require_permission("campaigns:manage"))) -> dict:
    c = db.get(Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    c.status = body.status
    db.commit()
    audit.record("CAMPAIGN_CHANGE", request=request, actor=who.user, resource_type="campaign", resource_id=cid,
                 detail={"op": "review", "status": body.status})
    return {"id": c.id, "status": c.status}


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    n_sessions = db.scalar(select(func.count(ScamSession.id))) or 0
    n_alerts = db.scalar(select(func.count(Alert.id))) or 0
    responses = Counter(r for (r,) in db.execute(select(Alert.response)).all())
    levels = Counter(lvl for (lvl,) in db.execute(select(Alert.level)).all())
    families = Counter(f for (f,) in db.execute(select(ScamSession.family_guess)).all() if f)
    return {
        "sessions": n_sessions,
        "alerts": n_alerts,
        "alerts_per_1000_sessions": round(1000 * n_alerts / n_sessions, 1) if n_sessions else 0.0,
        "alert_responses": {k or "no_response": v for k, v in responses.items()},
        "alerts_by_level": {str(k): v for k, v in sorted(levels.items())},
        "families": dict(families.most_common(10)),
        "testers": db.scalar(select(func.count(BetaTester.id))) or 0,
        "feedback": db.scalar(select(func.count(Feedback.id))) or 0,
        "campaigns": db.scalar(select(func.count(Campaign.id))) or 0,
    }
