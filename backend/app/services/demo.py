"""Demo scenarios, simulation on demand, the attacker-vs-defender arena, and campaign refresh."""

from __future__ import annotations

import random
from functools import lru_cache

import numpy as np

from chakravyuh.ml.train import first_payment_index
from chakravyuh.sim.agents import Genome, random_genome
from chakravyuh.sim.evolution import evaluate, genome_vector, next_generation
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


def arena(generations: int, population: int, per_genome: int, seed: int = 3) -> dict:
    """Evolve attackers against the current defender and report detection per generation."""
    sim = Chakravyuh(seed=seed)
    fams = [f for f in SCAM_FAMILIES]
    pop = [random_genome(sim.rng, fams, 1) for _ in range(population)]
    gate = 0.5
    eng = get_engine()
    if eng and eng.policy:
        gate = eng.policy.level_gates[1]
    seen: list[list[float]] = []
    history = []
    for gen in range(1, generations + 1):
        played = []
        for g in pop:
            g.generation = gen
            played.append((g, [sim.play(g, pool="test") for _ in range(per_genome)]))
        flat = [s for _, ss in played for s in ss]
        scores = engine_detector(flat)
        by_id = {s["session_id"]: float(sc > gate) for s, sc in zip(flat, scores)}
        avg_loss = sum(s["loss"] for s in flat) / max(len(flat), 1)
        detect = by_id.__getitem__
        scored = [evaluate(g, ss, lambda s, d=detect: d(s["session_id"]), seen, 0.5 * avg_loss) for g, ss in played]
        seen.extend(genome_vector(s.genome) for s in scored)
        missed = [s for s in flat if by_id[s["session_id"]] == 0.0 and s["paid"]]
        history.append({
            "generation": gen,
            "detection_rate": round(float(np.mean(list(by_id.values()))), 4),
            "mean_loss": round(avg_loss, 0),
            "missed_examples": [{"family": s["family"], "ops": s["genome"]["text_ops"],
                                 "extra_tactics": s["genome"]["extra_tactics"],
                                 "message": next((e["text"] for e in s["events"]
                                                  if e["type"] == "MSG_RECV" and e.get("text")), "")}
                                for s in missed[:3]],
            "top_genome": max(scored, key=lambda s: s.fitness).genome.to_dict(),
        })
        pop = next_generation(scored, sim.rng, gen + 1, fams, population)
        ARENA_STATE["elite"] = [s.genome for s in sorted(scored, key=lambda s: s.fitness, reverse=True)[:12]]
    return {"gate": gate, "history": history}


ARENA_STATE: dict = {"elite": []}


def _detection(engine, sessions: list[dict], gate: float) -> float:
    res = engine.decide(sessions)
    hits = []
    for r in res:
        k = first_payment_index(r["events"])
        ps = [d["p"] for d in r["decisions"][: (k + 1 if k is not None else None)]]
        hits.append(float((max(ps) if ps else 0.0) > gate))
    return float(np.mean(hits)) if hits else 0.0


def adapt(epochs: int = 3, seed: int = 5, persist: bool = False) -> dict:
    """Defender's turn: fine-tune ScamSeq on the attackers' newest tricks, then re-test on fresh variants."""
    import copy
    import json
    from pathlib import Path

    from chakravyuh.ml import scamseq as ss
    from chakravyuh.ml.features import encode_session

    from ..config import settings

    eng = get_engine()
    elite = ARENA_STATE.get("elite") or []
    if eng is None or not elite:
        return {"error": "Run the arena first (and make sure the model is loaded)."}
    gate = eng.policy.level_gates[1] if eng.policy else 0.5
    sim = Chakravyuh(seed=seed)
    evolved_train = [sim.play(copy.deepcopy(g), pool="train") for g in elite for _ in range(12)]
    legit = simulate(250, None, 0.0, seed=seed + 1)
    # Replay memory from the original training data so the model doesn't forget known scams.
    memory = []
    data_file = Path(settings.data_dir) / "sessions.jsonl"
    if data_file.exists():
        rng = random.Random(seed)
        lines = data_file.read_text(encoding="utf-8").splitlines()
        memory = [json.loads(x) for x in rng.sample(lines, min(1500, len(lines)))]
    fresh_test = [Chakravyuh(seed=seed + 7).play(copy.deepcopy(g), pool="test") for g in elite for _ in range(4)]
    legit_test = simulate(300, None, 0.0, seed=seed + 8)

    before = _detection(eng, fresh_test, gate)
    before_far = _detection(eng, legit_test, gate)

    train = evolved_train + legit + memory
    tags = eng.tag_events(train)
    enc = [encode_session(s, tags) for s in train]
    model = copy.deepcopy(eng.model)
    model.train()
    adapted = ss.finetune(model, enc, epochs=epochs)
    new_eng = copy.copy(eng)
    new_eng.model = adapted
    after = _detection(new_eng, fresh_test, gate)
    after_far = _detection(new_eng, legit_test, gate)
    if persist:
        ss.save(adapted, str(Path(settings.artifacts_dir) / "scamseq.pt"))
        get_engine.cache_clear()
    else:
        eng.model = adapted      # live for this server process, not written to disk
    return {"detection_before": round(before, 4), "detection_after": round(after, 4),
            "legit_false_alarm_before": round(before_far, 4), "legit_false_alarm_after": round(after_far, 4),
            "trained_on": {"evolved": len(evolved_train), "legit": len(legit), "replay": len(memory)},
            "tested_on": {"fresh_evolved": len(fresh_test), "legit": len(legit_test)}, "persisted": persist}
