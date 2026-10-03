"""Evaluation protocol for Sentinel (and baselines) on the v2 clean test files — per source, never merged.

    python sentinel/evaluate_cross_source.py --data sentinel/sft_real/sentinel_real_v2_clean \
        --pred <predictions dir> --out <metrics.json>

Decisions reported:
  1. argmax label (label_pred)
  2. threshold on p_scam selected on the UCI ham CALIBRATION half: smallest threshold flagging at most
     floor(1% x n) calibration messages (tie-aware), with a 500-sample bootstrap CI; applied unchanged to
     every source. The UCI EVALUATION half is the independent legitimate-FPR estimate.
  3. a threshold curve 0.05-0.999 with Wilson 95% CIs per source.
Sources: IMC'25 test (recall; scam_type/lures if generated), India test (legit and promo FPR),
UCI evaluation half (legit FPR), UCI spam (flag rate only), S&P'24 seen/novel (recall). Track: REAL.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cs", ROOT / "scripts" / "run_cross_source.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

FILES = {"imc25_test": "test_imc25_group_v1_test.jsonl", "india_test": "test_india_spam_sms_junioralive_group_v1_test.jsonl",
         "uci_ham_calibration": "test_uci_ham_calibration_v1_calibration.jsonl",
         "uci_ham_evaluation": "test_uci_ham_calibration_v1_evaluation.jsonl", "uci_spam": "test_uci_ham_calibration_v1_spam.jsonl",
         "sp24_seen": "test_sp24_temporal_v1_test_seen_campaign.jsonl", "sp24_novel": "test_sp24_temporal_v1_test_novel_campaign.jsonl"}


def load(data: Path, pred: Path, fname: str):
    gold = {json.loads(x)["meta"]["record_id"]: json.loads(x) for x in open(data / fname, encoding="utf-8")}
    P = [json.loads(x) for x in open(pred / fname, encoding="utf-8")]
    P = [p for p in P if p["record_id"] in gold]
    if len(P) != len(gold):
        raise SystemExit(f"{fname}: {len(P)} predictions for {len(gold)} examples")
    ys = np.array([gold[p["record_id"]]["meta"]["label"] for p in P])
    return gold, P, ys, np.array([p["p_scam"] for p in P], float), np.array([p.get("label_pred") or "legit" for p in P])


def select(scores, target=0.01):
    desc = np.sort(scores)[::-1]
    k = int(np.floor(target * len(desc)))
    return float(np.nextafter(desc[k], np.inf)) if k < len(desc) else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data, pred = Path(a.data), Path(a.pred)
    D = {k: load(data, pred, f) for k, f in FILES.items()}
    cal = D["uci_ham_calibration"][3]
    thr = select(cal)
    rng = np.random.default_rng(13)
    boots = [select(cal[rng.integers(0, len(cal), len(cal))]) for _ in range(500)]
    rep = {"track": "REAL PUBLIC DATA", "predictions": str(pred), "threshold": {
        "rule": "smallest threshold with <= floor(1% n) UCI-calibration ham flagged (tie-aware)",
        "value": thr, "bootstrap_95ci": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
        "calibration_n": int(len(cal))}, "per_source": {}, "curve": [], "latency_ms": {}}
    for k, (gold, P, ys, p, lab) in D.items():
        pred_t = np.where(p >= thr, "scam", np.where(lab == "scam", "legit", lab))
        blk = {"argmax": C.per_source_block(ys, p, lab), "calibrated_threshold": C.per_source_block(ys, p, pred_t)}
        sens = {}
        for name, ts in (("threshold_ci_low", rep["threshold"]["bootstrap_95ci"][0]), ("threshold_ci_high", rep["threshold"]["bootstrap_95ci"][1])):
            flag = p >= ts
            sens[name] = {"threshold": ts, "flag_rate": round(float(flag.mean()), 4)}
        blk["flag_rate_at_threshold_ci_ends"] = sens
        if k == "imc25_test":
            typed = [(gold[x["record_id"]], x) for x in P if x.get("parsed")]
            if typed:
                import sklearn.metrics as skm
                yt = [g["meta"]["scam_type"] for g, _ in typed]
                yp = [(x["parsed"] or {}).get("scam_type") or "none" for _, x in typed]
                blk["scam_type_macro_f1"] = round(float(skm.f1_score(yt, yp, average="macro", zero_division=0)), 4)
                blk["json_valid_rate"] = round(float(np.mean([x.get("json_valid") for x in P if x.get("json_valid") is not None])), 4)
            ind = np.array([gold[x["record_id"]]["meta"].get("country") == "IND" for x in P])
            blk["india_network_subset_recall"] = round(float((p[ind] >= thr).mean()), 4) if ind.any() else None
        rep["per_source"][k] = blk
        rep["latency_ms"][k] = round(float(np.median([x.get("latency_ms", np.nan) for x in P])), 3)
    for t in np.round(np.r_[np.arange(0.05, 0.95, 0.05), np.arange(0.95, 0.996, 0.005), [0.997, 0.998, 0.999]], 4):
        row = {"threshold": float(t)}
        for k in ("imc25_test", "sp24_seen", "sp24_novel", "uci_ham_evaluation", "uci_spam"):
            ys, p = D[k][2], D[k][3]
            n = int((p >= t).sum())
            row[k] = {"flag_rate": round(n / len(p), 4), "wilson_95ci": C.wilson(n, len(p))}
        ys, p = D["india_test"][2], D["india_test"][3]
        for c in ("legit", "promo"):
            n = int((p[ys == c] >= t).sum())
            row[f"india_{c}"] = {"flag_rate": round(n / max((ys == c).sum(), 1), 4), "wilson_95ci": C.wilson(n, int((ys == c).sum()))}
        rep["curve"].append(row)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=2) + "\n")
    s = {k: v["calibrated_threshold"] for k, v in rep["per_source"].items()}
    print(f"threshold {thr:.4f} CI {rep['threshold']['bootstrap_95ci']}")
    for k, v in s.items():
        print(f"  {k}: " + ", ".join(f"{m} {v[m]}" for m in ("recall", "fpr_legit", "fpr_promo", "uci_spam_flag_rate") if m in v))


if __name__ == "__main__":
    main()
