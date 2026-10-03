"""Evolutionary attacker: scams that steal money AND evade the defender survive.

F(g) = E[loss(g)] * (1 - p_detect(g)) - lambda * sim(g, seen)

`detector(session) -> probability` is any defender (rules today, the trained
models once they exist). Children are produced by mutation and crossover of genes.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable
from dataclasses import dataclass

from .agents import Genome
from .taxonomy import BENIGN_FAMILIES, SCAM_FAMILIES, TACTICS

Detector = Callable[[dict], float]


def genome_vector(g: Genome) -> list[float]:
    """Cheap structural embedding used for the novelty term."""
    v = [1.0 if g.family == f else 0.0 for f in SCAM_FAMILIES]
    v += [1.0 if t in g.extra_tactics else 0.0 for t in TACTICS]
    v += [1.0 if op in g.text_ops else 0.0 for op in ["synonym", "code_mix", "obfuscate", "typos", "emoji"]]
    v += [1.0 if g.borrow_contact else 0.0, 1.0 if g.swap_trust_pressure else 0.0, 0.5 * len(g.drop_stages)]
    v += [{"en": 0, "hi": 0.5, "hinglish": 1}[g.language]]
    return v


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def mutate(g: Genome, rng: random.Random, generation: int, families: list[str]) -> Genome:
    child = copy.deepcopy(g)
    child.genome_id = f"g{generation}-{rng.randrange(1 << 30):08x}"
    child.parent = g.genome_id
    child.generation = generation
    op = rng.choice(["text", "tactic", "borrow", "swap", "language", "channel", "amount", "pace", "drop"])
    if op == "text":
        choice = rng.choice(["synonym", "code_mix", "obfuscate", "typos", "emoji"])
        if choice not in child.text_ops:
            child.text_ops.append(choice)
    elif op == "tactic":
        t = rng.choice(TACTICS)
        if t in child.extra_tactics:
            child.extra_tactics.remove(t)
        else:
            child.extra_tactics.append(t)
    elif op == "borrow":
        donors = [f for f in families + BENIGN_FAMILIES if f != child.family]
        child.borrow_contact = rng.choice(donors)
    elif op == "drop":
        st = rng.choice(["hook", "trust", "pressure"])
        if st in child.drop_stages:
            child.drop_stages.remove(st)
        else:
            child.drop_stages.append(st)
    elif op == "swap":
        child.swap_trust_pressure = not child.swap_trust_pressure
    elif op == "language":
        child.language = rng.choice(["en", "hi", "hinglish"])
    elif op == "channel":
        child.channel = rng.choice(["sms", "whatsapp", "telegram", "email"])
    elif op == "amount":
        child.amount_scale = max(0.2, child.amount_scale * rng.uniform(0.4, 1.6))
    else:
        child.pace_scale = max(0.1, child.pace_scale * rng.uniform(0.3, 3.0))
    return child


def crossover(a: Genome, b: Genome, rng: random.Random, generation: int) -> Genome:
    child = copy.deepcopy(a)
    child.genome_id = f"g{generation}-{rng.randrange(1 << 30):08x}"
    child.parent = f"{a.genome_id}x{b.genome_id}"
    child.generation = generation
    child.text_ops = sorted(set(a.text_ops) | set(b.text_ops))
    child.extra_tactics = sorted(set(a.extra_tactics) | set(rng.sample(b.extra_tactics, k=len(b.extra_tactics) // 2)))
    donor = b.family if rng.random() < 0.5 else a.borrow_contact
    child.borrow_contact = donor if donor != child.family else None   # borrowing your own opener is no disguise
    return child


@dataclass
class Scored:
    genome: Genome
    fitness: float
    mean_loss: float
    p_detect: float
    novelty: float


def evaluate(genome: Genome, sessions: list[dict], detector: Detector, seen: list[list[float]],
             novelty_weight: float = 2000.0) -> Scored:
    if not sessions:
        return Scored(genome, 0.0, 0.0, 1.0, 0.0)
    mean_loss = sum(s["loss"] for s in sessions) / len(sessions)
    p_detect = sum(detector(s) for s in sessions) / len(sessions)
    vec = genome_vector(genome)
    sim = max((cosine(vec, s) for s in seen), default=0.0)
    fitness = mean_loss * (1 - p_detect) - novelty_weight * sim
    return Scored(genome, fitness, mean_loss, p_detect, 1 - sim)


def next_generation(scored: list[Scored], rng: random.Random, generation: int, families: list[str],
                    size: int, elite_frac: float = 0.2) -> list[Genome]:
    ranked = sorted(scored, key=lambda s: s.fitness, reverse=True)
    elite = [s.genome for s in ranked[: max(2, int(len(ranked) * elite_frac))]]
    children: list[Genome] = []
    while len(children) < size:
        if rng.random() < 0.3 and len(elite) > 1:
            a, b = rng.sample(elite, 2)
            children.append(crossover(a, b, rng, generation))
        else:
            children.append(mutate(rng.choice(elite), rng, generation, families))
    return children
