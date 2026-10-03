"""Attacker-defender co-evolution.

Each round:
  1. Attackers evolve for a few generations against the current defender (fitness = money stolen
     while undetected, plus novelty).
  2. The defender fine-tunes ScamSeq on sessions from the surviving attacker genomes, mixed with
     legitimate sessions and replayed training data so it doesn't forget known scams.
  3. Both are measured on FRESH sessions from those genomes (written with held-out wordings)
     and on legitimate sessions, before and after the defender's update.
  4. The attackers keep evolving from where they were, against the updated defender.

    python -m chakravyuh.ml.coevolve --rounds 3 --generations 4 --out reports/coevolution.json
    python -m chakravyuh.ml.coevolve --rounds 3 --persist     # also save the hardened model

The web arena uses the same Attacker and defend() so there is one implementation.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from pathlib import Path

import numpy as np

from ..sim.agents import Genome, random_genome
from ..sim.evolution import Scored, evaluate, genome_vector, next_generation
from ..sim.simulator import Chakravyuh
from ..sim.taxonomy import SCAM_FAMILIES
from . import scamseq as ss
from .engine import Engine
from .features import encode_session
from .tagger import TacticTagger


def first_payment_index(events: list[dict]) -> int | None:
    for i, e in enumerate(events):
        if e["type"] == "PAY" and not e["attrs"].get("cancelled") and e["attrs"].get("amount_ratio", 0) > 1.5:
            return i
    return None


def pre_payment_scores(engine: Engine, sessions: list[dict]) -> list[float]:
    """Highest fused risk before money leaves the account: what matters for prevention."""
    out = []
    for r in engine.decide(sessions):
        k = first_payment_index(r["events"])
        ps = [d["p"] for d in r["decisions"][: (k + 1 if k is not None else None)]]
        out.append(max(ps) if ps else 0.0)
    return out


def detection_rate(engine: Engine, sessions: list[dict], gate: float) -> float:
    if not sessions:
        return 0.0
    return float(np.mean([s > gate for s in pre_payment_scores(engine, sessions)]))


def alert_gate(engine: Engine) -> float:
    return engine.policy.level_gates[1] if engine.policy else 0.5


def _first_message(s: dict) -> str:
    return next((e["text"] for e in s["events"] if e["type"] == "MSG_RECV" and e.get("text")), "")


class Attacker:
    """A population of scam genomes that keeps evolving across rounds."""

    def __init__(self, population: int = 24, seed: int = 3, families: list[str] | None = None) -> None:
        self.sim = Chakravyuh(seed=seed)
        self.families = families or list(SCAM_FAMILIES)
        self.size = population
        self.pop: list[Genome] = [random_genome(self.sim.rng, self.families, 1) for _ in range(population)]
        self.seen: list[list[float]] = []
        self.generation = 0
        self.elite: list[Genome] = []

    def evolve(self, engine: Engine, generations: int, per_genome: int = 2) -> list[dict]:
        gate = alert_gate(engine)
        history = []
        for _ in range(generations):
            self.generation += 1
            played = []
            for g in self.pop:
                g.generation = self.generation
                played.append((g, [self.sim.play(g, pool="test") for _ in range(per_genome)]))
            flat = [s for _, ss_ in played for s in ss_]
            caught = {s["session_id"]: float(sc > gate) for s, sc in zip(flat, pre_payment_scores(engine, flat))}
            avg_loss = sum(s["loss"] for s in flat) / max(len(flat), 1)
            detect = caught.__getitem__
            scored: list[Scored] = [evaluate(g, ss_, lambda s, d=detect: d(s["session_id"]), self.seen,
                                             0.5 * avg_loss) for g, ss_ in played]
            self.seen.extend(genome_vector(s.genome) for s in scored)
            ranked = sorted(scored, key=lambda s: s.fitness, reverse=True)
            self.elite = [copy.deepcopy(s.genome) for s in ranked[:12]]
            missed = [s for s in flat if caught[s["session_id"]] == 0.0 and s["paid"]]
            history.append({
                "generation": self.generation,
                "detection_rate": round(float(np.mean(list(caught.values()))), 4),
                "mean_loss": round(avg_loss, 0),
                "missed_examples": [{"family": s["family"], "ops": s["genome"]["text_ops"],
                                     "extra_tactics": s["genome"]["extra_tactics"], "message": _first_message(s)}
                                    for s in missed[:3]],
                "top_genome": ranked[0].genome.to_dict(),
            })
            self.pop = next_generation(scored, self.sim.rng, self.generation + 1, self.families, self.size)
        return history


LEVEL_EPS = [None, 0.005, 0.005, 0.001, 0.001]   # false-alarm cap per alert level (same as training)


def recalibrate_gates(engine: Engine, legit: list[dict]) -> list[float]:
    """Conformal gates from the highest score each legitimate session ever reaches.

    After the model changes, old thresholds no longer mean what they claimed. Recomputing them on
    fresh legitimate sessions restores each level's cap: P(alert at level L | legit) <= eps_L.
    """
    peaks = np.sort([max((d["p"] for d in r["decisions"]), default=0.0) for r in engine.decide(legit)])
    n = len(peaks)
    gates = [0.0]
    for eps in LEVEL_EPS[1:]:
        k = min(n - 1, int(np.ceil((n + 1) * (1 - eps))) - 1)
        gates.append(float(peaks[k]))
    return gates


def replay_memory(data_dir: str | Path, n: int = 1500, seed: int = 0) -> list[dict]:
    f = Path(data_dir) / "sessions.jsonl"
    if not f.exists():
        return []
    lines = f.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in random.Random(seed).sample(lines, min(n, len(lines)))]


def defend(engine: Engine, elite: list[Genome], replay: list[dict], epochs: int = 4, seed: int = 5,
           train_per_genome: int = 24, test_per_genome: int = 4, refit_tagger: bool = True) -> tuple[Engine, dict]:
    """Fine-tune the defender on the attackers' newest tricks. Returns the updated engine and a report."""
    gate = alert_gate(engine)
    sim = Chakravyuh(seed=seed)
    evolved_train = [sim.play(copy.deepcopy(g), pool="train") for g in elite for _ in range(train_per_genome)]
    legit_train = Chakravyuh(seed=seed + 1).base_dataset(250, scam_ratio=0.0)
    test_sim = Chakravyuh(seed=seed + 7)
    fresh_test = [test_sim.play(copy.deepcopy(g), pool="test") for g in elite for _ in range(test_per_genome)]
    legit_test = Chakravyuh(seed=seed + 8).base_dataset(300, scam_ratio=0.0, pool="test")

    before, before_far = detection_rate(engine, fresh_test, gate), detection_rate(engine, legit_test, gate)
    train = evolved_train + legit_train + replay
    updated = copy.copy(engine)
    if refit_tagger and replay:
        # The message tagger learns the new wording too (replay keeps the old families in view).
        updated.tagger = TacticTagger().fit(train)
    tags = updated.tag_events(train)
    model = ss.finetune(copy.deepcopy(engine.model), [encode_session(s, tags) for s in train], epochs=epochs,
                        log=lambda *_: None)
    updated.model = model
    if engine.policy:
        updated.policy = copy.deepcopy(engine.policy)
        # calibrate on recent-looking traffic (held-out wordings, different seed from the test batch)
        legit_cal = Chakravyuh(seed=seed + 9).base_dataset(600, scam_ratio=0.0, pool="test")
        updated.policy.level_gates = recalibrate_gates(updated, legit_cal)
        updated.policy.min_p_for_hold = updated.policy.level_gates[3]
    new_gate = alert_gate(updated)
    after, after_far = detection_rate(updated, fresh_test, new_gate), detection_rate(updated, legit_test, new_gate)
    # Champion/challenger: ship the update only if it catches more attacks without breaking the
    # false-alarm cap (allowing 1 point of noise). Otherwise keep the current model.
    accepted = after > before and after_far <= max(before_far, 0.01) + 0.01
    result = updated if accepted else engine
    return result, {
        "accepted": accepted,
        "detection_before": round(before, 4), "detection_after": round(after, 4),
        "legit_false_alarm_before": round(before_far, 4), "legit_false_alarm_after": round(after_far, 4),
        "trained_on": {"evolved": len(evolved_train), "legit": len(legit_train), "replay": len(replay)},
        "tested_on": {"fresh_evolved": len(fresh_test), "legit": len(legit_test)},
        "gate_before": round(gate, 4), "gate_after": round(new_gate, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run attacker-defender co-evolution")
    ap.add_argument("--artifacts", default="artifacts")
    ap.add_argument("--data", default="data")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--generations", type=int, default=4, help="attacker generations per round")
    ap.add_argument("--population", type=int, default=24)
    ap.add_argument("--epochs", type=int, default=4, help="defender fine-tuning epochs per round")
    ap.add_argument("--out", default="reports/coevolution.json")
    ap.add_argument("--persist", action="store_true", help="save the hardened ScamSeq into --artifacts")
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    t0 = time.time()
    engine = Engine.load(args.artifacts)
    attacker = Attacker(args.population, seed=args.seed)
    replay = replay_memory(args.data)
    rounds = []
    for r in range(1, args.rounds + 1):
        hist = attacker.evolve(engine, args.generations)
        print(f"round {r}: attacker detection by generation "
              + " -> ".join(f"{h['detection_rate']:.0%}" for h in hist))
        engine, report = defend(engine, attacker.elite, replay, epochs=args.epochs, seed=args.seed + 10 * r)
        verdict = "update shipped" if report["accepted"] else "update rejected, kept current model"
        print(f"         defender: caught {report['detection_before']:.0%} -> {report['detection_after']:.0%} of "
              f"fresh attacks; legit false alarms {report['legit_false_alarm_before']:.1%} -> "
              f"{report['legit_false_alarm_after']:.1%} ({verdict})")
        rounds.append({"round": r, "attacker": hist, "defender": report})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rounds": rounds, "seconds": round(time.time() - t0, 1)}, indent=2))
    if args.persist:
        ss.save(engine.model, str(Path(args.artifacts) / "scamseq.pt"))
        import pickle
        with open(Path(args.artifacts) / "tagger.pkl", "wb") as f:
            pickle.dump(engine.tagger, f)
        if engine.policy:
            (Path(args.artifacts) / "policy.json").write_text(json.dumps(engine.policy.to_dict()))
        print(f"saved hardened model and recalibrated gates to {args.artifacts}/")
    print(f"wrote {out} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
