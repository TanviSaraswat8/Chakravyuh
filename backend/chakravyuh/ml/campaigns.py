"""Emerging-campaign detection.

1. Prototypes mu_c = mean embedding of each known scam family (from training data).
2. A risky session is "unknown" if 1 - cos(e, mu_c) > delta for every known family.
3. Unknown sessions are clustered with HDBSCAN; a big enough cluster becomes a campaign card.
4. PSI on tactic frequencies flags drift between this week and training data.
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA

from ..sim.taxonomy import TACTICS


def _norm(x: np.ndarray) -> np.ndarray:
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9, None)


class CampaignDetector:
    def __init__(self, delta: float = 0.15, min_cluster: int = 8) -> None:
        self.delta = delta
        self.min_cluster = min_cluster
        self.prototypes: dict[str, np.ndarray] = {}
        self.train_tactic_freq: dict[str, float] = {}

    def fit(self, embeddings: np.ndarray, families: list[str], labels: list[int], tactic_lists: list[list[str]]):
        E = _norm(embeddings)
        for fam in sorted({f for f, lab in zip(families, labels) if lab == 1}):
            m = np.array([f == fam for f in families])
            self.prototypes[fam] = _norm(E[m].mean(0))
        self.train_tactic_freq = self._freq(tactic_lists)
        # Pick delta so that ~97% of known-family sessions are within their nearest prototype.
        scam = np.array(labels) == 1
        d = self.distance(embeddings[scam])
        if len(d):
            self.delta = float(np.quantile(d, 0.97))
        return self

    def distance(self, embeddings: np.ndarray) -> np.ndarray:
        if not self.prototypes:
            return np.ones(len(embeddings))
        P = np.stack(list(self.prototypes.values()))
        return (1 - _norm(embeddings) @ P.T).min(1)

    def nearest_family(self, embeddings: np.ndarray) -> list[str]:
        names = list(self.prototypes)
        P = np.stack(list(self.prototypes.values()))
        return [names[i] for i in (_norm(embeddings) @ P.T).argmax(1)]

    def is_unknown(self, embeddings: np.ndarray, p: np.ndarray, p_min: float = 0.3) -> np.ndarray:
        return (p > p_min) & (self.distance(embeddings) > self.delta)

    def cluster(self, sessions: list[dict], embeddings: np.ndarray) -> list[dict]:
        if len(sessions) < self.min_cluster:
            return []
        X = _norm(embeddings)
        if X.shape[1] > 10 and len(X) > 12:
            X = PCA(n_components=10, random_state=0).fit_transform(X)
        # allow_single_cluster: one new campaign on its own must still produce a card
        labels = HDBSCAN(min_cluster_size=self.min_cluster, allow_single_cluster=True, copy=True).fit_predict(X)
        cards = []
        for c in sorted(set(labels) - {-1}):
            members = [s for s, lab in zip(sessions, labels) if lab == c]
            cards.append(self.card(members, c))
        return cards

    @staticmethod
    def card(members: list[dict], cid: int) -> dict:
        tac = Counter(t for s in members for e in s["events"] for t in e.get("tags", e.get("tactics", [])))
        types = Counter(e["type"] for s in members for e in s["events"])
        langs = Counter(s.get("language", "?") for s in members)
        chans = Counter(s.get("channel", "?") for s in members)
        payees = Counter(e["attrs"].get("payee") for s in members for e in s["events"]
                         if e["type"] == "PAY" and e["attrs"].get("payee"))
        seq = []
        for e in members[0]["events"]:
            if e["type"] not in ("MSG_SENT",) and (not seq or seq[-1] != e["type"]):
                seq.append(e["type"])
        top_tac = [t for t, _ in tac.most_common(4)]
        example = next((e["text"] for e in members[0]["events"] if e["type"] == "MSG_RECV" and e.get("text")), "")
        name = " + ".join(t.replace("_", " ") for t in top_tac[:2]) or "unlabelled pattern"
        return {
            "campaign_id": f"C{cid:03d}",
            "name": f"New pattern: {name} via {chans.most_common(1)[0][0]}",
            "size": len(members),
            "top_tactics": top_tac,
            "event_sequence": seq[:10],
            "languages": dict(langs),
            "channels": dict(chans),
            "payee_clusters": [p for p, _ in payees.most_common(5)],
            "example_message": example[:240],
            "draft_rule": ("ALERT if session has " + " AND ".join(f"tactic:{t}" for t in top_tac[:3])
                           + (" AND event:LINK_OPEN" if types.get("LINK_OPEN") else "")
                           + (" AND event:PAYEE_NEW" if types.get("PAYEE_NEW") else "")),
            "session_ids": [s["session_id"] for s in members[:50]],
        }

    @staticmethod
    def _freq(tactic_lists: list[list[str]]) -> dict[str, float]:
        c = Counter(t for ts in tactic_lists for t in ts)
        total = sum(c.values()) or 1
        return {t: (c.get(t, 0) + 1) / (total + len(TACTICS)) for t in TACTICS}

    def psi(self, tactic_lists: list[list[str]]) -> float:
        a = self._freq(tactic_lists)
        e = self.train_tactic_freq
        return float(sum((a[t] - e[t]) * math.log(a[t] / e[t]) for t in TACTICS))

    def to_dict(self) -> dict:
        return {"delta": self.delta, "min_cluster": self.min_cluster,
                "prototypes": {k: v.tolist() for k, v in self.prototypes.items()},
                "train_tactic_freq": self.train_tactic_freq}

    @classmethod
    def from_dict(cls, d: dict) -> CampaignDetector:
        c = cls(d["delta"], d["min_cluster"])
        c.prototypes = {k: np.array(v) for k, v in d["prototypes"].items()}
        c.train_tactic_freq = d["train_tactic_freq"]
        return c
