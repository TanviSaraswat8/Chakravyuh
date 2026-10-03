"""Demo helpers: scripted scenarios, on-demand simulation, the attacker-vs-defender arena."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from chakravyuh.ml.features import payment_rows

from ..config import MAX_ADAPT_EPOCHS
from ..deps import Principal, require_permission, step_up
from ..schemas import ArenaRequest, SimulateRequest
from ..security import audit, ratelimit
from ..services.demo import SCENARIOS, adapt, arena, scenario, simulate
from ..services.scoring import score_session

router = APIRouter(prefix="/v1/demo", tags=["demo"])


@router.get("/scenarios")
def list_scenarios() -> list[dict]:
    return [{"key": k, "title": v["title"], "kind": v["kind"], "blurb": v["blurb"]} for k, v in SCENARIOS.items()]


@router.get("/scenarios/{key}", dependencies=[Depends(ratelimit.by_ip("scenario_ip"))])
def get_scenario(key: str) -> dict:
    if key not in SCENARIOS:
        raise HTTPException(404, "Unknown scenario")
    sc = scenario(key)
    scored = score_session(sc["events"], sc["language"], sc["channel"])
    # A bank-style per-transaction rule for comparison: flags any payment over 20x the usual amount.
    baseline = []
    for e in sc["events"]:
        flag = e["type"] == "PAY" and e["attrs"].get("amount_ratio", 0) > 20
        baseline.append({"alert": bool(flag)})
    return {**sc, "scores": scored["steps"], "alerts": {str(k): v for k, v in scored["alerts"].items()},
            "family_guess": scored["family_guess"], "baseline": baseline}


@router.post("/simulate", dependencies=[Depends(ratelimit.by_ip("simulate_ip"))])
def run_simulation(req: SimulateRequest) -> dict:
    sessions = simulate(req.n, req.families, req.scam_ratio)
    out = []
    for s in sessions:
        sc = score_session(s["events"], s["language"], s["channel"])
        out.append({"session_id": s["session_id"], "family": s["family"], "label": s["label"],
                    "language": s["language"], "n_events": len(s["events"]), "paid": s["paid"],
                    "max_p": max((st["p"] for st in sc["steps"]), default=0.0),
                    "max_level": max((st["level"] for st in sc["steps"]), default=0),
                    "payments": len(payment_rows(s))})
    return {"n": len(out), "sessions": out}


@router.post("/arena", dependencies=[Depends(ratelimit.by_ip("arena_ip"))])
def run_arena(req: ArenaRequest) -> dict:
    """Attackers evolve against the current defender. Public demo: rate-limited, one run at a time.
    It only simulates attacks; it never changes the defender model."""
    with ratelimit.model_ops:
        return arena(req.generations, req.population, req.per_genome, fresh=req.fresh)


@router.post("/arena/adapt")
def run_adapt(request: Request,
              epochs: int = Query(3, ge=1, le=MAX_ADAPT_EPOCHS,
                                  description=f"defender fine-tuning epochs, 1-{MAX_ADAPT_EPOCHS}"),
              persist: bool = False,
              p: Principal = Depends(require_permission("model:adapt"))) -> dict:
    """Defender's turn: learn from the attackers' newest tricks, then re-test on fresh variants.

    MODEL_ENGINEER only. The accepted update replaces the live in-memory defender. persist=true also
    overwrites the model files on disk and needs model:persist plus a password re-entry within the
    last few minutes (POST /v1/auth/reauth).
    """
    if persist:
        step_up(request, p, "model:persist")
    ratelimit.enforce("adapt_user", p.id)
    with ratelimit.model_ops:
        report = adapt(epochs=epochs, persist=persist)
    if "error" not in report:
        detail = {"epochs": epochs, "accepted": report.get("accepted"),
                  "detection_before": report.get("detection_before"),
                  "detection_after": report.get("detection_after")}
        audit.record("MODEL_ADAPT", request=request, actor=p.user, resource_type="model", resource_id="scamseq",
                     detail=detail)
        if persist:
            audit.record("MODEL_PERSIST", "success" if report.get("persisted") else "failure", request=request,
                         actor=p.user, resource_type="model", resource_id="scamseq",
                         reason=None if report.get("persisted") else "update not accepted, nothing written",
                         detail=detail)
    return report
