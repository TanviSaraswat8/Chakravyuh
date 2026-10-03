"""Alert policy: learning *when* to speak and how strongly.

Contextual bandit (LinUCB) over escalation levels 1-4, with "stay quiet" fixed at reward 0.
The ladder only moves up within a session. A Lagrange multiplier lambda enforces the alert
budget B (alerts per 1,000 sessions):

    a* = argmax_a ( theta_a . s + alpha * sqrt(s^T A_a^-1 s) - lambda * 1[a escalates] )
    lambda <- max(0, lambda + eta * (alerts_used - B))

Rewards come from the simulator, where we know if a session is a scam and how much is at stake:
    scam, before payment : amount * (STOP[a] - STOP[current])  - small annoyance
    legit                : -(FRICTION[a] - FRICTION[current])
    scam, after payment  : -0.2 * FRICTION[a]   (too late to help)
"""

from __future__ import annotations

import math
import random

import numpy as np

STOP = [0.0, 0.35, 0.55, 0.75, 0.90]        # chance an alert at this level stops the victim
FRICTION = [0.0, 0.05, 0.25, 1.2, 3.0]     # cost to a legitimate user, in thousand-rupee units
LEVEL_NAMES = ["silent_log", "nudge", "interactive_check", "cooling_off", "trusted_contact_hold"]


def context(p: float, stage_payment_prob: float, tau_log: float, amount_ratio: float,
            current_level: int, dismissed: int = 0) -> np.ndarray:
    return np.array([1.0, p, p * p, stage_payment_prob, max(tau_log, 0.0) / 14.0,
                     math.log1p(amount_ratio) / 6.0, current_level / 4.0, min(dismissed, 5) / 5.0])


D = 8


class LinUCBPolicy:
    def __init__(self, alpha: float = 0.5, budget_per_1000: float = 300.0, eta: float = 0.002) -> None:
        self.alpha = alpha
        self.budget = budget_per_1000
        self.eta = eta
        self.lam = 0.0
        self.A = [np.eye(D) for _ in range(5)]
        self.b = [np.zeros(D) for _ in range(5)]
        self.min_p_for_hold = 0.5      # safety guard for levels 3-4, set from conformal threshold
        # Conformal gate per level: P(p > gate_L | legit) <= eps_L, so each level has a false-alarm cap.
        self.level_gates = [0.0, 0.5, 0.6, 0.7, 0.8]

    def _theta(self, a: int) -> np.ndarray:
        return np.linalg.solve(self.A[a], self.b[a])

    def scores(self, s: np.ndarray, explore: bool = False) -> list[float]:
        out = [0.0]
        for a in range(1, 5):
            est = float(self._theta(a) @ s)
            if explore:
                est += self.alpha * math.sqrt(float(s @ np.linalg.solve(self.A[a], s)))
            out.append(est - self.lam)
        return out

    @staticmethod
    def max_level(payment_pending: bool, stage_payment_prob: float) -> int:
        """Structural limits: a hold needs a payment to hold; a check needs one to be coming."""
        if payment_pending:
            return 4
        if stage_payment_prob > 0.5:
            return 2
        return 1

    def act(self, s: np.ndarray, current: int, p: float, explore: bool = False,
            payment_pending: bool = True) -> int:
        sc = self.scores(s, explore)
        best, best_v = current, 0.0
        cap = self.max_level(payment_pending, float(s[3]))
        for a in range(current + 1, cap + 1):
            if p <= self.level_gates[a] or (a >= 3 and p <= self.min_p_for_hold):
                continue
            if sc[a] > best_v:
                best, best_v = a, sc[a]
        return best

    def update(self, s: np.ndarray, a: int, r: float) -> None:
        self.A[a] += np.outer(s, s)
        self.b[a] += r * s

    @staticmethod
    def reward(level: int, current: int, label: int, paid_already: bool, amount_k: float) -> float:
        if label == 1 and not paid_already:
            return amount_k * (STOP[level] - STOP[current]) - 0.02 * level
        if label == 1:
            return -0.2 * FRICTION[level]
        return -(FRICTION[level] - FRICTION[current])

    def fit(self, traces: list[dict], epochs: int = 3, seed: int = 0, log=print) -> LinUCBPolicy:
        """traces: per session {label, amount_k, steps: [(p, stage_pay, tau, ratio, paid_already, pending)]}."""
        rng = random.Random(seed)
        for ep in range(epochs):
            order = list(range(len(traces)))
            rng.shuffle(order)
            alerts, sessions = 0, 0
            for i in order:
                tr = traces[i]
                cur = 0
                for (p, sp, tau, ratio, paid, pending) in tr["steps"]:
                    s = context(p, sp, tau, ratio, cur)
                    a = self.act(s, cur, p, explore=True, payment_pending=pending)
                    # also learn from one random counterfactual escalation (cheap off-policy signal)
                    cap = self.max_level(pending, sp)
                    cf = rng.randint(cur + 1, cap) if cur < cap else None
                    if cf is not None:
                        self.update(s, cf, self.reward(cf, cur, tr["label"], paid, tr["amount_k"]))
                    if a > cur:
                        self.update(s, a, self.reward(a, cur, tr["label"], paid, tr["amount_k"]))
                        alerts += 1
                        cur = a
                sessions += 1
                if sessions % 200 == 0:
                    rate = 1000 * alerts / sessions
                    self.lam = max(0.0, self.lam + self.eta * (rate - self.budget))
            rate = 1000 * alerts / max(sessions, 1)
            log(f"  policy epoch {ep + 1}: alerts/1000 sessions={rate:.0f} lambda={self.lam:.3f}")
        return self

    def to_dict(self) -> dict:
        return {"A": [a.tolist() for a in self.A], "b": [b.tolist() for b in self.b], "lam": self.lam,
                "alpha": self.alpha, "budget": self.budget, "min_p_for_hold": self.min_p_for_hold,
                "level_gates": self.level_gates}

    @classmethod
    def from_dict(cls, d: dict) -> LinUCBPolicy:
        p = cls(alpha=d["alpha"], budget_per_1000=d["budget"])
        p.A = [np.array(a) for a in d["A"]]
        p.b = [np.array(b) for b in d["b"]]
        p.lam = d["lam"]
        p.min_p_for_hold = d["min_p_for_hold"]
        p.level_gates = d.get("level_gates", p.level_gates)
        return p
