"""Evaluation protocol for Sentinel (and baselines) on the clean test files (v2 and v3 builds share them
byte-for-byte) — per source, never merged.

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
Precision, PR-AUC, ROC-AUC and ECE need both classes, so they are reported for named source PAIRS
(one scam source vs one legitimate source) at the same threshold — never as a merged headline. Pair
precision depends on that pair's prevalence and is not a deployment precision.
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
OPTIONAL_FILES = {"moz_test": "test_moz_smishing_eval_all_v1_test.jsonl"}


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
    files = dict(FILES)
    if (data / OPTIONAL_FILES["moz_test"]).exists():      # v4+: evaluation-only external test (MOZ-Smishing)
        files.update(OPTIONAL_FILES)
    D = {k: load(data, pred, f) for k, f in files.items()}
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
    thr_ci = rep["threshold"]["bootstrap_95ci"]
    rep["pairs"] = {}
    for pos_k, neg_k, neg_c in (("imc25_test", "uci_ham_evaluation", "legit"), ("imc25_test", "india_test", "legit"),
                                ("imc25_test", "india_test", "promo"), ("sp24_novel", "uci_ham_evaluation", "legit"),
                                ("sp24_seen", "uci_ham_evaluation", "legit"), ("sp24_novel", "india_test", "promo")):
        p_pos = D[pos_k][3][D[pos_k][2] == "scam"]
        p_neg = D[neg_k][3][D[neg_k][2] == neg_c]
        blk = C.pair_block(p_pos, p_neg, thr)
        y = np.r_[np.ones(len(p_pos), bool), np.zeros(len(p_neg), bool)]
        flag = np.r_[p_pos, p_neg] >= thr
        blk["confusion_at_threshold"] = {"tp": int((flag & y).sum()), "fn": int((~flag & y).sum()),
                                         "fp": int((flag & ~y).sum()), "tn": int((~flag & ~y).sum())}
        rep["pairs"][f"{pos_k}__vs__{neg_k}_{neg_c}"] = blk
    for k in D:
        lat = np.array([x.get("latency_ms", np.nan) for x in D[k][1]], float)
        rep["latency_ms"][k] = {"p50": round(float(np.nanmedian(lat)), 3), "p95": round(float(np.nanpercentile(lat, 95)), 3),
                                "note": "per message within a batched forward pass"}
    single = pred / "latency_single.json"
    if single.exists():
        rep["latency_ms"]["single_message_batch1"] = json.loads(single.read_text())
    for t in np.round(np.r_[np.arange(0.05, 0.95, 0.05), np.arange(0.95, 0.996, 0.005), [0.997, 0.998, 0.999]], 4):
        row = {"threshold": float(t)}
        for k in ("imc25_test", "sp24_seen", "sp24_novel", "uci_ham_evaluation", "uci_spam"):
            ys, p = D[k][2], D[k][3]
            n = int((p >= t).sum())
            row[k] = {"flag_rate": round(n / len(p), 4), "wilson_95ci": C.wilson(n, len(p))}
        if "moz_test" in D:
            ys, p = D["moz_test"][2], D["moz_test"][3]
            for c in ("scam", "legit"):
                n = int((p[ys == c] >= t).sum())
                row[f"moz_{c}"] = {"flag_rate": round(n / max((ys == c).sum(), 1), 4), "wilson_95ci": C.wilson(n, int((ys == c).sum()))}
        ys, p = D["india_test"][2], D["india_test"][3]
        for c in ("legit", "promo"):
            n = int((p[ys == c] >= t).sum())
            row[f"india_{c}"] = {"flag_rate": round(n / max((ys == c).sum(), 1), 4), "wilson_95ci": C.wilson(n, int((ys == c).sum()))}
        rep["curve"].append(row)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=2) + "\n")
    s = {k: v["calibrated_threshold"] for k, v in rep["per_source"].items()}
    print(f"threshold {thr:.4f} CI {thr_ci}")
    for k, v in s.items():
        print(f"  {k}: " + ", ".join(f"{m} {v[m]}" for m in ("recall", "fpr_legit", "fpr_promo", "uci_spam_flag_rate") if m in v))
    for k, v in rep["pairs"].items():
        print(f"  pair {k}: precision {v['precision']} pr_auc {v['pr_auc']} ece {v['ece']}")


if __name__ == "__main__":
    main()
