"""Score predictions against the REAL-data SFT test files. Works for Sentinel and for any baseline that
writes the same predictions format ({record_id, parsed: {label, scam_type, lures, p_scam?}, latency_ms}).

    python sentinel/evaluate_real.py --data sentinel/sft_real/sentinel_real_v1 \
        --pred sentinel/outputs/sentinel_real_v1/predictions --out sentinel/outputs/sentinel_real_v1/metrics_real.json

Every report is stamped track=REAL. Simulator results are produced elsewhere and never merged.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chakravyuh.realdata import metrics  # noqa: E402

LURES = ["authority", "time/urgency", "distraction", "need and greed", "kindness", "herd", "dishonesty"]


def p_scam(parsed: dict | None) -> float:
    if not parsed:
        return 0.5
    if isinstance(parsed.get("p_scam"), (int, float)):
        return float(parsed["p_scam"])
    return 1.0 if parsed.get("label") == "scam" else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    report = {"track": "REAL", "data": a.data, "tests": {}}
    for f in sorted(Path(a.data).glob("test_*.jsonl")):
        pf = Path(a.pred) / f.name
        if not pf.exists():
            continue
        gold = {json.loads(x)["meta"]["record_id"]: json.loads(x) for x in open(f, encoding="utf-8")}
        preds = [json.loads(x) for x in open(pf, encoding="utf-8")]
        preds = [p for p in preds if p["record_id"] in gold]
        y = [int(gold[p["record_id"]]["meta"]["label"] == "scam") for p in preds]
        res = {"n": len(preds), "json_valid": sum(p.get("json_valid", True) for p in preds) / max(len(preds), 1),
               "scam_vs_rest": metrics.detection(y, [p_scam(p.get("parsed")) for p in preds]),
               "latency": metrics.latency([p["latency_ms"] for p in preds if "latency_ms" in p])}
        typed = [p for p in preds if gold[p["record_id"]]["meta"]["typed"] and gold[p["record_id"]]["meta"]["label"] == "scam"]
        if typed:
            res["scam_type"] = metrics.multiclass([gold[p["record_id"]]["meta"]["scam_type"] for p in typed],
                                                  [(p.get("parsed") or {}).get("scam_type") for p in typed])
            gl = [json.loads(gold[p["record_id"]]["messages"][2]["content"])["lures"] for p in typed]
            res["lures_vs_gpt4o_labels"] = metrics.multilabel(gl, [(p.get("parsed") or {}).get("lures") or [] for p in typed], LURES)
        by_lang = defaultdict(lambda: ([], []))
        for p in preds:
            lang = gold[p["record_id"]]["meta"].get("language") or "unknown"
            by_lang[lang][0].append(int(gold[p["record_id"]]["meta"]["label"] == "scam"))
            by_lang[lang][1].append(p_scam(p.get("parsed")))
        res["by_language"] = {k: metrics.detection(v[0], v[1]) for k, v in by_lang.items() if len(v[0]) >= 30}
        report["tests"][f.stem] = res
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: {"n": v["n"], "recall": v["scam_vs_rest"]["recall"], "fpr": v["scam_vs_rest"]["fpr"]}
                      for k, v in report["tests"].items()}, indent=1))


if __name__ == "__main__":
    main()
