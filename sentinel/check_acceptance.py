"""Apply the pre-registered Sentinel acceptance criteria (docs/SENTINEL_TRAINING_PLAN.md, section 9) mechanically.

    python sentinel/check_acceptance.py --sentinel <run>/metrics_real.json \
        --baseline sentinel/baselines/sentinel_real_v3_scam8k/chakravyuh_tagger_arch/metrics.json --out <run>/acceptance.json

All five criteria are evaluated at the calibrated threshold that evaluate_cross_source.py chose on the UCI ham
calibration half. Nothing here can change that threshold. The criteria and their limits are fixed constants:
editing them after Sentinel results exist would break the pre-registration.
Exit code 0 = all criteria pass, 1 = at least one fails (or cannot be evaluated).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

UCI_FPR_MAX, UCI_FPR_CI_HIGH_MAX = 0.015, 0.025
PROMO_FPR_MAX = 0.05
IMC_RECALL_MARGIN = 0.03
SP24_NOVEL_RECALL_MIN = 0.90
JSON_VALID_MIN = 0.99

PASS_WORDING = ("Sentinel v2 passed the pre-registered evaluation criteria on held-out public real-world "
                "message datasets.")


def cal(m: dict, src: str) -> dict:
    return m["per_source"][src]["calibrated_threshold"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentinel", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    S = json.loads(Path(a.sentinel).read_text())
    B = json.loads(Path(a.baseline).read_text())
    crit = []

    u = cal(S, "uci_ham_evaluation")
    crit.append({"id": 1, "criterion": f"UCI ham evaluation FPR <= {UCI_FPR_MAX} and 95% CI upper <= {UCI_FPR_CI_HIGH_MAX}",
                 "value": u["fpr_legit"], "ci": u["fpr_legit_95ci"],
                 "pass": u["fpr_legit"] <= UCI_FPR_MAX and u["fpr_legit_95ci"][1] <= UCI_FPR_CI_HIGH_MAX})

    i = cal(S, "india_test")
    crit.append({"id": 2, "criterion": f"India promotional FPR <= {PROMO_FPR_MAX}",
                 "value": i["fpr_promo"], "ci": i["fpr_promo_95ci"], "pass": i["fpr_promo"] <= PROMO_FPR_MAX})

    s_imc, b_imc = cal(S, "imc25_test"), cal(B, "imc25_test")
    need = round(b_imc["recall"] + IMC_RECALL_MARGIN, 4)
    crit.append({"id": 3, "criterion": f"IMC'25 recall >= baseline + {IMC_RECALL_MARGIN} with non-overlapping bootstrap CIs",
                 "value": s_imc["recall"], "ci": s_imc["recall_95ci"], "baseline": b_imc["recall"],
                 "baseline_ci": b_imc["recall_95ci"], "required": need,
                 "pass": s_imc["recall"] >= need and s_imc["recall_95ci"][0] > b_imc["recall_95ci"][1]})

    n = cal(S, "sp24_novel")
    crit.append({"id": 4, "criterion": f"S&P'24 novel-campaign recall >= {SP24_NOVEL_RECALL_MIN}",
                 "value": n["recall"], "ci": n["recall_95ci"], "pass": n["recall"] >= SP24_NOVEL_RECALL_MIN})

    jv = S["per_source"]["imc25_test"].get("json_valid_rate")
    crit.append({"id": 5, "criterion": f"JSON validity >= {JSON_VALID_MIN} on generated IMC'25 outputs",
                 "value": jv, "pass": jv is not None and jv >= JSON_VALID_MIN,
                 **({"note": "no generated outputs found: cannot pass"} if jv is None else {})})

    # Reported alongside, never used to override a failed criterion.
    side = {}
    for src, keys in (("india_test", ("fpr_legit", "fpr_promo")), ("uci_ham_evaluation", ("fpr_legit",)),
                      ("uci_spam", ("uci_spam_flag_rate",)), ("sp24_seen", ("recall",)),
                      ("sp24_novel", ("recall",)), ("imc25_test", ("recall",))):
        side[src] = {k: {"sentinel": cal(S, src).get(k), "baseline": cal(B, src).get(k)} for k in keys}
    side["thresholds"] = {"sentinel": S["threshold"], "baseline": B["threshold"]}
    false_alarm_up = [f"{src}.{k}" for src, d in side.items() if src != "thresholds"
                      for k, v in d.items() if k.startswith("fpr") and v["sentinel"] is not None
                      and v["baseline"] is not None and v["sentinel"] > v["baseline"]]

    passed = all(c["pass"] for c in crit)
    verdict = PASS_WORDING if passed else (
        "Sentinel did NOT pass the pre-registered criteria (failed: "
        + ", ".join(str(c["id"]) for c in crit if not c["pass"])
        + "). It is not reported as an improvement; the frozen character model remains the reference.")
    rep = {"track": "REAL PUBLIC DATA", "preregistered_in": "docs/SENTINEL_TRAINING_PLAN.md section 9",
           "criteria": crit, "all_pass": passed, "verdict": verdict,
           "reported_alongside_not_criteria": side,
           "false_alarm_rates_higher_than_baseline": false_alarm_up,
           "claims_not_made": ["real-world deployment validation", "UPI detection", "session-level detection",
                               "payment prediction", "Hindi/Hinglish capability", "victim behaviour prediction"]}
    Path(a.out).write_text(json.dumps(rep, indent=2) + "\n")
    for c in crit:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['id']}. {c['criterion']}: {c['value']}")
    if false_alarm_up:
        print("  false-alarm rates above baseline:", ", ".join(false_alarm_up))
    print(verdict)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
