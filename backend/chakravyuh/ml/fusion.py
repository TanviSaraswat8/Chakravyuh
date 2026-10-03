"""Late fusion + calibration + conformal false-alarm control.

z = w . [logit p_seq, logit p_msg, logit r_payee, context flags] + b
p = sigmoid(a * z + c)           Platt scaling on held-out data (isotonic is available too, but its
                                 step function makes thresholds tie, so conformal gates can't separate)
q_eps = (1 - eps) quantile of p over legitimate calibration sessions  =>  P(p > q | legit) <= eps
"""

from __future__ import annotations

import math

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

FUSION_FEATURES = ["logit_seq", "logit_msg", "logit_payee", "call_unknown", "screen_share",
                   "remote_app", "new_payee", "log_amount_ratio", "stage_payment_prob"]


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def context_row(p_seq: float, p_msg: float, r_payee: float, flags: dict, stage_payment_prob: float) -> list[float]:
    return [_logit(p_seq), _logit(p_msg), _logit(r_payee),
            float(flags.get("call_unknown", 0)), float(flags.get("screen_share", 0)),
            float(flags.get("remote_app", 0)), float(flags.get("new_payee", 0)),
            math.log1p(flags.get("amount_ratio", 0.0)), stage_payment_prob]


class Fusion:
    def __init__(self, calibration: str = "platt") -> None:
        self.lr = LogisticRegression(max_iter=2000, C=1.0)
        self.calibration = calibration
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.platt = LogisticRegression(max_iter=1000, C=100.0)
        self.thresholds: dict[str, float] = {}

    def _calibrate(self, raw: np.ndarray) -> np.ndarray:
        if self.calibration == "isotonic":
            return self.iso.predict(raw)
        z = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / np.clip(1 - raw, 1e-6, 1)).reshape(-1, 1)
        return self.platt.predict_proba(z)[:, 1]

    def fit(self, X: np.ndarray, y: np.ndarray, X_cal: np.ndarray, y_cal: np.ndarray,
            groups_cal: np.ndarray | None = None) -> Fusion:
        self.lr.fit(X, y)
        raw = self.lr.predict_proba(X_cal)[:, 1]
        if self.calibration == "isotonic":
            self.iso.fit(raw, y_cal)
        else:
            z = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / np.clip(1 - raw, 1e-6, 1)).reshape(-1, 1)
            self.platt.fit(z, y_cal)
        cal = self._calibrate(raw)
        if groups_cal is not None:
            # Session-level conformal: a legit session gets many chances to cross a threshold,
            # so calibrate on the max score per legitimate session.
            legit = np.sort(np.array([cal[(groups_cal == g)].max() for g in np.unique(groups_cal[y_cal == 0])]))
        else:
            legit = np.sort(cal[y_cal == 0])
        n = len(legit)
        for eps in (0.001, 0.005, 0.01, 0.02, 0.05, 0.1):
            k = min(n - 1, int(math.ceil((n + 1) * (1 - eps))) - 1)
            self.thresholds[str(eps)] = float(legit[k]) if n else 0.5
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._calibrate(self.lr.predict_proba(X)[:, 1])

    def weights(self) -> dict[str, float]:
        return {k: round(float(w), 3) for k, w in zip(FUSION_FEATURES, self.lr.coef_[0])}


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)
