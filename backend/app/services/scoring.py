"""Loads the trained engine once and turns a session into a decision for its newest event."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

from chakravyuh.ml.engine import Engine
from chakravyuh.ml.integrity import IntegrityError
from chakravyuh.sim.simulator import rule_detector

from ..config import settings
from .alert_text import reason_code, render

log = logging.getLogger("chakravyuh")
_LOAD_ERROR: dict[str, str] = {}


@lru_cache(maxsize=1)
def get_engine() -> Engine | None:
    path = Path(settings.artifacts_dir)
    if not (path / "scamseq.pt").exists():
        log.warning("No trained artifacts in %s; running in rules-only fallback mode", path)
        return None
    try:
        return Engine.load(path)
    except IntegrityError as e:
        # Never fall back to loading unverified files. Run rules-only and say why in /health.
        log.error("Model artifacts refused: %s", e)
        _LOAD_ERROR["reason"] = str(e)
        from ..security import audit
        audit.record("MODEL_LOAD_FAILURE", "failure", resource_type="model", resource_id=str(path)[-64:],
                     reason=str(e))
        return None


def model_status() -> dict:
    e = get_engine()
    if e is None:
        out = {"loaded": False, "mode": "rules_fallback"}
        if _LOAD_ERROR:
            out["integrity_error"] = _LOAD_ERROR["reason"]
        return out
    return {"loaded": True, "mode": "chakravyuh", "trained_at": e.meta.get("trained_at"),
            "n_train": e.meta.get("n_train"), "gates": e.policy.level_gates if e.policy else None}


def _overrides(events: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Events that arrive with on-device tags but no text get a placeholder key for those tags."""
    out, tags = [], {}
    for i, e in enumerate(events):
        e = dict(e)
        if e["type"] == "MSG_RECV" and not e.get("text") and e.get("client_tags"):
            key = f"__client_tag_{i}__"
            e["text"] = key
            tags[key] = {"tactics": e["client_tags"].get("tactics", []),
                         "p_scam": float(e["client_tags"].get("p_scam", 0.0)),
                         "stage": e["client_tags"].get("stage", "contact"), "tactic_probs": {}}
        out.append(e)
    return out, tags


def score_session(events: list[dict], language: str = "en", channel: str = "whatsapp") -> dict:
    """Score every event; returns per-event decisions plus the alert (if any) for the newest event."""
    session = {"events": events, "language": language, "channel": channel, "label": 0}
    engine = get_engine()
    if engine is None:
        p = rule_detector(session)
        return {"mode": "rules_fallback", "steps": [{"p": p, "level": 1 if p > 0.5 else 0}] * len(events),
                "latest": {"p": p, "level": 1 if p > 0.5 else 0, "escalated": p > 0.5},
                "alert": None, "alerts": {}, "family_guess": None, "embedding": None}
    evs, overrides = _overrides(events)
    res = engine.decide([{**session, "events": evs}], tag_overrides=overrides)[0]
    decisions = res["decisions"]
    tags = res["tags"]
    family = None
    if engine.campaigns and engine.campaigns.prototypes:
        family = engine.campaigns.nearest_family(np.array([res["embedding"]]))[0]
    steps = []
    alerts: dict[int, dict] = {}
    tactics_so_far: set[str] = set()
    for i, (e, d) in enumerate(zip(evs, decisions)):
        tag = tags.get(e.get("text") or "", {})
        tactics_so_far |= set(tag.get("tactics", []))
        steps.append({"p": round(d["p"], 4), "level": d["level"], "escalated": d["escalated"],
                      "action": d["action"], "next_stage": d["next_stage"],
                      "p_seq": round(d["p_seq"], 4), "p_msg": round(d["p_msg"], 4),
                      "r_payee": round(d["r_payee"], 4), "tactics": tag.get("tactics", []),
                      "stage_guess": tag.get("stage"), "msg_p": round(float(tag.get("p_scam", 0.0)), 4)})
        if d["escalated"]:
            code = reason_code(tactics_so_far, d["flags"], family if d["p"] > 0.5 else None, evs[: i + 1])
            title, message = render(code, d["level"], language)
            alerts[i] = {"level": d["level"], "action": d["action"], "reason_code": code,
                         "title": title, "message": message, "p": round(d["p"], 4)}
    latest = steps[-1] if steps else {"p": 0.0, "level": 0, "escalated": False}
    alert = alerts.get(len(steps) - 1)
    return {"mode": "chakravyuh", "steps": steps, "latest": latest, "alert": alert, "alerts": alerts,
            "family_guess": family if latest["p"] > 0.5 else None,
            "embedding": [round(float(x), 5) for x in res["embedding"]]}
