"""Message tactic tagger (Sentinel-lite).

A fast character n-gram model that reads one message and returns the same JSON
shape as the Sentinel SLM: tactics, stage and a scam probability. It is the
server-side fallback and the teacher-free baseline; the fine-tuned SLM in
`sentinel/` replaces it on device. Character n-grams handle Hindi, Hinglish,
typos and leetspeak without a tokenizer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

from ..sim.taxonomy import STAGES, TACTICS


@dataclass
class TagResult:
    tactics: list[str]
    tactic_probs: dict[str, float]
    stage: str
    p_scam: float

    def to_dict(self) -> dict:
        return {"tactics": self.tactics, "tactic_probs": self.tactic_probs,
                "stage": self.stage, "p_scam": self.p_scam}


class TacticTagger:
    def __init__(self, threshold: float = 0.4) -> None:
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2,
                                   sublinear_tf=True, max_features=60000)
        self.tactic_clf = OneVsRestClassifier(LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"))
        self.stage_clf = LogisticRegression(max_iter=2000, C=4.0)
        self.scam_clf = LogisticRegression(max_iter=2000, C=2.0, class_weight="balanced")
        self.threshold = threshold

    @staticmethod
    def examples(sessions: list[dict]) -> tuple[list[str], np.ndarray, list[str], np.ndarray]:
        texts, tac, stages, scam = [], [], [], []
        for s in sessions:
            for e in s["events"]:
                if e["type"] == "MSG_RECV" and e.get("text"):
                    texts.append(e["text"])
                    tac.append([1 if t in e["tactics"] else 0 for t in TACTICS])
                    stages.append(e["stage"])
                    # a borrowed genuine opener is not scam text, even inside a scam session
                    scam.append(0 if e.get("attrs", {}).get("disguise") else s["label"])
        return texts, np.array(tac), stages, np.array(scam)

    def fit(self, sessions: list[dict]) -> TacticTagger:
        texts, tac, stages, scam = self.examples(sessions)
        X = self.vec.fit_transform(texts)
        keep = tac.sum(axis=0) > 0
        self.active = [t for t, k in zip(TACTICS, keep) if k]
        self.tactic_clf.fit(X, tac[:, keep])
        self.stage_clf.fit(X, stages)
        self.scam_clf.fit(X, scam)
        return self

    def tag_many(self, texts: list[str]) -> list[TagResult]:
        if not texts:
            return []
        X = self.vec.transform(texts)
        tp = self.tactic_clf.predict_proba(X)
        st = self.stage_clf.predict(X)
        ps = self.scam_clf.predict_proba(X)[:, 1]
        out = []
        for i in range(len(texts)):
            probs = {t: round(float(p), 3) for t, p in zip(self.active, tp[i])}
            out.append(TagResult([t for t, p in probs.items() if p >= self.threshold], probs, str(st[i]),
                                 round(float(ps[i]), 4)))
        return out

    def tag(self, text: str) -> TagResult:
        return self.tag_many([text])[0]


def tactic_vector(tactics: list[str]) -> list[float]:
    return [1.0 if t in tactics else 0.0 for t in TACTICS]


__all__ = ["TacticTagger", "TagResult", "tactic_vector", "STAGES"]
