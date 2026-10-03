"""Demo helpers: scripted scenarios, on-demand simulation, the attacker-vs-defender arena."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from chakravyuh.ml.features import payment_rows

from ..schemas import ArenaRequest, SimulateRequest
from ..services.demo import SCENARIOS, adapt, arena, scenario, simulate
from ..services.scoring import score_session

router = APIRouter(prefix="/v1/demo", tags=["demo"])


@router.get("/scenarios")
def list_scenarios() -> list[dict]:
    return [{"key": k, "title": v["title"], "kind": v["kind"], "blurb": v["blurb"]} for k, v in SCENARIOS.items()]


@router.get("/scenarios/{key}")
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


@router.post("/simulate")
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


@router.post("/arena")
def run_arena(req: ArenaRequest) -> dict:
    return arena(req.generations, req.population, req.per_genome)


@router.post("/arena/adapt")
def run_adapt(epochs: int = 3, persist: bool = False) -> dict:
    """Defender's turn: learn from the attackers' newest tricks, then re-test on fresh variants."""
    return adapt(epochs=epochs, persist=persist)
