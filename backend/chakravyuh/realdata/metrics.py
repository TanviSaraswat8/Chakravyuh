"""Evaluation metrics for the real-data track. Positive-only test sets get recall only: precision,
FPR and ROC/PR-AUC are undefined without negatives and are reported as null, never estimated."""

from __future__ import annotations

from collections import Counter

import numpy as np
from sklearn.metrics import average_precision_score, f1_score, precision_recall_fscore_support, roc_auc_score


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


def detection(y_true: list[int], p_scam: list[float], threshold: float = 0.5) -> dict:
    y, p = np.asarray(y_true, dtype=int), np.asarray(p_scam, dtype=float)
    pred = (p >= threshold).astype(int)
    tp, fn = int(((pred == 1) & (y == 1)).sum()), int(((pred == 0) & (y == 1)).sum())
    fp, tn = int(((pred == 1) & (y == 0)).sum()), int(((pred == 0) & (y == 0)).sum())
    both = len(set(y.tolist())) == 2
    out = {"n": int(len(y)), "positives": int(y.sum()), "negatives": int((y == 0).sum()), "threshold": threshold,
           "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
           "recall": tp / (tp + fn) if tp + fn else None, "fnr": fn / (tp + fn) if tp + fn else None,
           "precision": tp / (tp + fp) if both and tp + fp else None,
           "fpr": fp / (fp + tn) if both and fp + tn else None,
           "pr_auc": float(average_precision_score(y, p)) if both else None,
           "roc_auc": float(roc_auc_score(y, p)) if both else None,
           "ece": ece(y, p) if both else None}
    if out["precision"] is not None and out["recall"] is not None:
        pr, rc = out["precision"], out["recall"]
        out["f1"] = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    else:
        out["f1"] = None
    if not both:
        out["note"] = "single-class test set: only recall/FNR are defined"
    return out


def multiclass(y_true: list[str], y_pred: list[str | None]) -> dict:
    labels = sorted(set(y_true))
    pred = [p if p is not None else "__none__" for p in y_pred]
    p, r, f, s = precision_recall_fscore_support(y_true, pred, labels=labels, zero_division=0)
    conf = Counter(zip(y_true, pred))
    return {"macro_f1": float(np.mean(f)), "accuracy": float(np.mean([a == b for a, b in zip(y_true, pred)])),
            "per_class": {lab: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]),
                                "support": int(s[i])} for i, lab in enumerate(labels)},
            "confusion": {f"{a} -> {b}": c for (a, b), c in conf.most_common(30)}}


def multilabel(y_true: list[list[str]], y_pred: list[list[str]], vocab: list[str]) -> dict:
    Y = np.array([[int(v in t) for v in vocab] for t in y_true])
    P = np.array([[int(v in t) for v in vocab] for t in y_pred])
    per = f1_score(Y, P, average=None, zero_division=0)
    return {"micro_f1": float(f1_score(Y, P, average="micro", zero_division=0)),
            "macro_f1": float(f1_score(Y, P, average="macro", zero_division=0)),
            "per_label_f1": {v: float(x) for v, x in zip(vocab, per)}}


def latency(ms: list[float]) -> dict:
    if not ms:
        return {}
    a = np.asarray(ms)
    return {"p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)), "mean_ms": float(a.mean())}
