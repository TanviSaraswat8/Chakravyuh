"""Gate between the 50-message smoke test and the full training run. Pipeline checks only, not quality.

    python sentinel/smoke_check.py --run sentinel/outputs/sentinel_real_v3_scam8k_smoke \
        --data sentinel/sft_real/sentinel_real_v3_scam8k --n 50

Fails (exit 1) if any of these is false — the notebook then STOPS before full training:
  1. training_log.json exists, mode == smoke, loss finite, loss mask check passed (finetune.py enforces it).
  2. the adapter was saved (lora/adapter_model.safetensors).
  3. every test file has exactly min(n, rows) predictions, with matching record ids.
  4. every p_label is finite, non-negative and sums to 1 (+-1e-3); label_pred is one of scam/promo/legit.
  5. JSON generation ran on every IMC'25 smoke example (a raw output string exists).
  6. a batch-1 latency measurement was written.
JSON validity after a few smoke steps is REPORTED, not gated: the pre-registered >= 99% applies to the full run.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

LABELS = {"scam", "promo", "legit"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()
    run, data = Path(a.run), Path(a.data)
    fails: list[str] = []
    log_p = run / "training_log.json"
    if not log_p.exists():
        fails.append("training_log.json missing")
    else:
        log = json.loads(log_p.read_text())
        if log.get("mode") != "smoke":
            fails.append(f"training_log mode is {log.get('mode')!r}, expected 'smoke'")
        if not all(math.isfinite(x) for x in (log.get("first_train_loss", float("nan")), log.get("final_train_loss", float("nan")))):
            fails.append("non-finite training loss")
        print(f"  training: {log.get('global_steps')} steps, loss {log.get('first_train_loss')} -> {log.get('final_train_loss')}, "
              f"{log.get('precision')}, GPU {log.get('hardware', {}).get('gpu')}, tokens over max-seq {log.get('train_tokens_over_max_seq')}")
    if not (run / "lora" / "adapter_model.safetensors").exists():
        fails.append("adapter not saved")
    pred = run / "predictions"
    jv = None
    for f in sorted(data.glob("test_*.jsonl")):
        want = [json.loads(x)["meta"]["record_id"] for x in open(f, encoding="utf-8")][: a.n]
        p = pred / f.name
        if not p.exists():
            fails.append(f"no predictions for {f.name}")
            continue
        P = [json.loads(x) for x in open(p, encoding="utf-8")]
        if [x["record_id"] for x in P] != want:
            fails.append(f"{f.name}: {len(P)} predictions / ids do not match the first {len(want)} examples")
        for x in P:
            pl = x.get("p_label") or {}
            vals = [pl.get(k) for k in ("scam", "promo", "legit")]
            if None in vals or not all(math.isfinite(v) and v >= 0 for v in vals) or abs(sum(vals) - 1) > 1e-3:
                fails.append(f"{f.name}: bad p_label {pl}")
                break
            if x.get("label_pred") not in LABELS:
                fails.append(f"{f.name}: bad label_pred {x.get('label_pred')!r}")
                break
        if f.name == "test_imc25_group_v1_test.jsonl":
            if any("raw" not in x for x in P):
                fails.append("JSON generation did not run on every IMC'25 smoke example")
            else:
                jv = sum(bool(x.get("json_valid")) for x in P) / max(len(P), 1)
                print(f"  IMC'25 smoke JSON validity (reported, not gated): {jv:.3f}; example: {P[0]['raw'][:120]!r}")
        print(f"  {f.name}: {len(P)} predictions, mean p_scam {sum(x['p_scam'] for x in P) / max(len(P), 1):.3f}")
    if not (pred / "latency_single.json").exists():
        fails.append("latency_single.json missing")
    else:
        print("  latency (batch 1):", json.loads((pred / "latency_single.json").read_text()))
    report = {"passed": not fails, "failures": fails, "smoke_json_validity": jv}
    (run / "smoke_check.json").write_text(json.dumps(report, indent=2) + "\n")
    print("SMOKE TEST PASSED" if not fails else "SMOKE TEST FAILED — STOP, do not run full training:\n  - " + "\n  - ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
