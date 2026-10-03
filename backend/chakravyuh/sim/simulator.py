"""Chakravyuh: the self-evolving scam simulator.

Usage:
    python -m chakravyuh.sim.simulator --n 4000 --generations 5 --out data/

Writes:
    data/sessions.jsonl       one labelled session per line (generation 0 + evolved generations)
    data/ledger.csv           every transfer in the payment sandbox (for the payee-risk model)
    data/accounts.csv         account kinds and ages (mule labels for the graph model)
    data/evolution.json       fitness / detection rate per generation
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Callable
from pathlib import Path

from .agents import Genome, Victim, random_genome, run_session
from .evolution import evaluate, genome_vector, next_generation
from .llm import LLMClient
from .sandbox import PaymentSandbox
from .taxonomy import BENIGN_FAMILIES, SCAM_FAMILIES

DAY = 86400.0


def rule_detector(session: dict) -> float:
    """Keyword-and-threshold defender: what a typical bank rule engine does today."""
    score = 0.0
    for e in session["events"]:
        txt = (e.get("text") or "").lower()
        if any(k in txt for k in ["otp", "kyc", "digital arrest", "blocked", "anydesk", "tax"]):
            score += 0.25
        if e["type"] == "PAY" and e["attrs"].get("amount_ratio", 0) > 50:
            score += 0.4
    return min(score, 1.0)


class Chakravyuh:
    def __init__(self, seed: int = 7, llm_rate: float = 0.0) -> None:
        self.rng = random.Random(seed)
        self.sandbox = PaymentSandbox(self.rng)
        self.sandbox.build_world()
        self.sandbox.background_traffic(6000, 0, 30 * DAY)
        self.llm = LLMClient()
        self.llm_rate = llm_rate
        self.clock = 30 * DAY

    def _victim(self, language: str) -> Victim:
        return Victim.sample(self.rng, self.rng.choice(self.sandbox.users()), language)

    def play(self, genome: Genome, warn_fn=None, pool: str = "train") -> dict:
        self.clock += self.rng.uniform(60, 3 * 3600)
        return run_session(genome, self._victim(genome.language), self.sandbox, self.rng, self.clock,
                           self.llm, self.llm_rate, warn_fn, pool)

    def base_dataset(self, n: int, scam_ratio: float = 0.45, scam_families: list[str] | None = None,
                     pool: str = "train") -> list[dict]:
        scam_families = scam_families or SCAM_FAMILIES
        out = []
        for _ in range(n):
            fams = scam_families if self.rng.random() < scam_ratio else BENIGN_FAMILIES
            out.append(self.play(random_genome(self.rng, fams), pool=pool))
        return out

    def evolve(self, generations: int, population: int, sessions_per_genome: int,
               detector: Callable[[dict], float], families: list[str]) -> tuple[list[dict], list[dict]]:
        pop = [random_genome(self.rng, families, 0) for _ in range(population)]
        seen: list[list[float]] = []
        all_sessions: list[dict] = []
        history: list[dict] = []
        for gen in range(1, generations + 1):
            played = []
            for g in pop:
                g.generation = gen
                pool = "test" if gen > generations - 2 else "train"
                sess = [self.play(g, pool=pool) for _ in range(sessions_per_genome)]
                all_sessions.extend(sess)
                played.append((g, sess))
            # Novelty weight scaled to this generation's typical loss so neither term dominates.
            avg_loss = sum(s["loss"] for _, ss in played for s in ss) / max(1, sum(len(ss) for _, ss in played))
            scored = [evaluate(g, sess, detector, seen, novelty_weight=0.5 * avg_loss) for g, sess in played]
            seen.extend(genome_vector(s.genome) for s in scored)
            det = sum(s.p_detect for s in scored) / len(scored)
            loss = sum(s.mean_loss for s in scored) / len(scored)
            best = max(scored, key=lambda s: s.fitness)
            history.append({"generation": gen, "mean_detection": round(det, 4), "mean_loss": round(loss, 2),
                            "best_fitness": round(best.fitness, 2), "best_genome": best.genome.to_dict()})
            print(f"  gen {gen}: detection={det:.3f} mean_loss={loss:,.0f} best={best.genome.family}"
                  f" ops={best.genome.text_ops} tactics+={best.genome.extra_tactics}")
            pop = next_generation(scored, self.rng, gen + 1, families, population)
        return all_sessions, history

    def export(self, out: Path, sessions: list[dict], history: list[dict]) -> None:
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "sessions.jsonl", "w", encoding="utf-8") as f:
            for s in sessions:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        with open(out / "ledger.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["src", "dst", "amount", "t", "first_time", "session_id"])
            for t in self.sandbox.ledger:
                w.writerow([t.src, t.dst, t.amount, round(t.t, 1), int(t.first_time), t.session_id or ""])
        with open(out / "accounts.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["vpa", "kind", "created_day", "devices", "is_mule"])
            for a in self.sandbox.accounts.values():
                w.writerow([a.vpa, a.kind, a.created_day, a.devices, int(a.kind.startswith("mule"))])
        (out / "evolution.json").write_text(json.dumps(history, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Chakravyuh simulator")
    ap.add_argument("--n", type=int, default=4000, help="generation-0 sessions")
    ap.add_argument("--generations", type=int, default=5)
    ap.add_argument("--population", type=int, default=40)
    ap.add_argument("--per-genome", type=int, default=3)
    ap.add_argument("--holdout", default="echallan_link", help="scam family kept out of training")
    ap.add_argument("--llm-rate", type=float, default=0.0, help="share of messages rewritten by the LLM")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    sim = Chakravyuh(seed=args.seed, llm_rate=args.llm_rate)
    train_fams = [f for f in SCAM_FAMILIES if f != args.holdout]
    print(f"Generation 0: {args.n} sessions (holdout family: {args.holdout})")
    base = sim.base_dataset(args.n, scam_families=train_fams)
    for s in base:
        s["split_hint"] = "train_pool"
    test = sim.base_dataset(max(200, args.n // 4), scam_families=train_fams, pool="test")
    for s in test:
        s["split_hint"] = "test_seen"
    held = sim.base_dataset(max(100, args.n // 20), scam_ratio=1.0, scam_families=[args.holdout], pool="test")
    for s in held:
        s["split_hint"] = "holdout_family"
    print(f"Evolving {args.generations} generations x {args.population} genomes")
    evolved, history = sim.evolve(args.generations, args.population, args.per_genome, rule_detector, train_fams)
    for s in evolved:
        s["split_hint"] = "evolved"
    sim.export(Path(args.out), base + test + held + evolved, history)
    total = len(base) + len(test) + len(held) + len(evolved)
    print(f"Wrote {total} sessions, {len(sim.sandbox.ledger)} transfers to {args.out}/")


if __name__ == "__main__":
    main()
