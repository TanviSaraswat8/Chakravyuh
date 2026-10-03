"""Demo scenarios, simulation on demand, the attacker-vs-defender arena, and campaign refresh."""

from __future__ import annotations

import json
import random
from functools import lru_cache

from chakravyuh.ml.coevolve import Attacker, alert_gate, defend, first_payment_index, replay_memory
from chakravyuh.sim.agents import Genome, random_genome
from chakravyuh.sim.simulator import Chakravyuh
from chakravyuh.sim.taxonomy import BENIGN_FAMILIES, SCAM_FAMILIES

from .scoring import get_engine

SCENARIOS = {
    "investment_group": {"title": "AI-run investment group", "kind": "scam",
                         "blurb": "A slow-burn trading-group scam over several days, with fake profits.",
                         "genome": dict(family="investment_group", language="hinglish", channel="whatsapp")},
    "echallan_link": {"title": "Never-seen e-challan scam", "kind": "scam",
                      "blurb": "A scam family the models were never trained on.",
                      "genome": dict(family="echallan_link", language="en", channel="sms")},
    "task_job": {"title": "Part-time task job", "kind": "scam",
                 "blurb": "Small payouts first, then 'prepaid tasks' and frozen earnings.",
                 "genome": dict(family="task_job", language="en", channel="telegram")},
    "mule_recruitment": {"title": "Student recruited as a mule", "kind": "scam",
                         "blurb": "Warns the account holder before they forward stolen money.",
                         "genome": dict(family="mule_recruitment", language="hinglish", channel="whatsapp")},
    "digital_arrest": {"title": "Digital arrest", "kind": "scam",
                       "blurb": "Fake officials keep the victim on a video call.",
                       "genome": dict(family="digital_arrest", language="en", channel="call")},
    "big_purchase": {"title": "Legit: flat deposit to a new payee", "kind": "legit",
                     "blurb": "Large urgent payment to someone new. Should stay quiet.",
                     "genome": dict(family="big_purchase", language="en", channel="whatsapp")},
    "new_number_family": {"title": "Legit: family on a new number", "kind": "legit",
                          "blurb": "Looks like the classic 'new number' scam, but it is real.",
                          "genome": dict(family="new_number_family", language="hinglish", channel="whatsapp")},
}


def speaker(etype: str) -> str:
    return {"MSG_RECV": "them", "MSG_SENT": "me"}.get(etype, "system")


@lru_cache(maxsize=32)
def scenario(key: str, seed: int = 11) -> dict:
    spec = SCENARIOS[key]
    sim = Chakravyuh(seed=seed)
    for _ in range(40):   # pick a run where the scam reaches the payment step (a complete story)
        s = sim.play(Genome(**spec["genome"]), pool="test")
        if spec["kind"] == "legit" or any(e["type"] == "PAY" for e in s["events"]):
            break
    events = [{**e, "speaker": speaker(e["type"])} for e in s["events"]]
    return {"key": key, **{k: v for k, v in spec.items() if k != "genome"}, "language": s["language"],
            "channel": s["channel"], "events": events}


def simulate(n: int, families: list[str] | None, scam_ratio: float, seed: int | None = None) -> list[dict]:
    sim = Chakravyuh(seed=seed if seed is not None else random.randrange(1 << 30))
    rng = sim.rng
    out = []
    for _ in range(n):
        if families:
            fams = families
        else:
            fams = SCAM_FAMILIES if rng.random() < scam_ratio else BENIGN_FAMILIES
        out.append(sim.play(random_genome(rng, fams), pool="test"))
    return out


def engine_detector(sessions: list[dict]) -> list[float]:
    """Defender used in the arena: max fused probability before money leaves."""
    eng = get_engine()
    if eng is None:
        from chakravyuh.sim.simulator import rule_detector
        return [rule_detector(s) for s in sessions]
    res = eng.decide(sessions)
    out = []
    for r in res:
        k = first_payment_index(r["events"])
        ps = [d["p"] for d in r["decisions"][: (k + 1 if k is not None else None)]]
        out.append(max(ps) if ps else 0.0)
    return out


ARENA_STATE: dict = {"attacker": None, "history": [], "defences": []}


def arena(generations: int, population: int, per_genome: int, fresh: bool = True, seed: int = 3) -> dict:
    """Attackers' turn. fresh=True starts a new arms race; False continues against the current defender."""
    eng = get_engine()
    if eng is None:
        return {"error": "Model not loaded."}
    if fresh or ARENA_STATE["attacker"] is None:
        ARENA_STATE.update(attacker=Attacker(population, seed=seed), history=[], defences=[])
    hist = ARENA_STATE["attacker"].evolve(eng, generations, per_genome)
    round_no = len(ARENA_STATE["defences"]) + 1
    for h in hist:
        h["round"] = round_no
    ARENA_STATE["history"].extend(hist)
    return {"gate": alert_gate(eng), "round": round_no, "history": ARENA_STATE["history"],
            "defences": ARENA_STATE["defences"]}


def adapt(epochs: int = 3, seed: int = 5, persist: bool = False) -> dict:
    """Defender's turn: fine-tune on the attackers' newest tricks, recalibrate the alert gates, and ship
    the update only if it catches more attacks without breaking the false-alarm cap."""
    from pathlib import Path

    from chakravyuh.ml import scamseq as ss

    from ..config import settings

    eng = get_engine()
    attacker = ARENA_STATE.get("attacker")
    if eng is None or attacker is None or not attacker.elite:
        return {"error": "Run the attackers first (and make sure the model is loaded)."}
    updated, report = defend(eng, attacker.elite, replay_memory(settings.data_dir), epochs=epochs,
                             seed=seed + 10 * len(ARENA_STATE["defences"]))
    if report["accepted"]:
        # swap the live engine's parts in place, so every request in this process uses the new defender
        eng.model, eng.policy = updated.model, updated.policy
        if persist:
            ss.save(eng.model, str(Path(settings.artifacts_dir) / "scamseq.pt"))
            if eng.policy:
                (Path(settings.artifacts_dir) / "policy.json").write_text(json.dumps(eng.policy.to_dict()))
    report["persisted"] = bool(persist and report["accepted"])
    report["round"] = len(ARENA_STATE["defences"]) + 1
    ARENA_STATE["defences"].append(report)
    return report
