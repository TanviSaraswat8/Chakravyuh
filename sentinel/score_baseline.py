"""Score a frozen E3 baseline on Sentinel's exact SFT test files (CPU), in the predictions format used by
evaluate_cross_source.py, so Sentinel and the baseline are compared on identical messages.

    python sentinel/score_baseline.py --model e3__clean__chakravyuh_tagger_arch \
        --data sentinel/sft_real/sentinel_real_v2_clean --out sentinel/baselines/sentinel_real_v2_clean/chakravyuh_tagger_arch
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cs", ROOT / "scripts" / "run_cross_source.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    model, man = C.load_artifact(a.model)             # SHA-256 checked against its manifest
    name = a.model.split("__")[-1]
    cal = C.svm_calibrator(model) if name == "tfidf_svm" else None
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(a.data).glob("test_*.jsonl")):
        rows = [json.loads(x) for x in open(f, encoding="utf-8")]
        texts = [r["messages"][1]["content"].removeprefix("Message:\n") for r in rows]
        t0 = time.perf_counter()
        p, pred = C.model_scores(model, name, texts, cal)
        ms = (time.perf_counter() - t0) * 1000 / max(len(texts), 1)
        with open(out / f.name, "w", encoding="utf-8") as w:
            for r, ps, pr in zip(rows, p, pred):
                w.write(json.dumps({"record_id": r["meta"]["record_id"], "p_scam": float(ps), "label_pred": str(pr),
                                    "parsed": None, "latency_ms": ms}) + "\n")
        print(f"{f.name}: {len(rows)} (mean p_scam {float(np.mean(p)):.3f})")
    (out / "SOURCE.json").write_text(json.dumps({"model": a.model, "artifact_sha256": man["sha256"],
                                                 "label": "REAL PUBLIC DATA baseline (frozen E3 model)"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
