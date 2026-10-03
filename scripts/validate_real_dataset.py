#!/usr/bin/env python3
"""Validate registered real datasets without modifying them.

    python scripts/validate_real_dataset.py imc25_smishing sp24_gateway_phishing
    python scripts/validate_real_dataset.py --all          # every dataset with files on disk

Writes data/reports/<dataset_id>.validation.json. Exit code 1 if any dataset has a hard failure
(manifest incomplete, SHA-256 mismatch, missing files, invalid labels).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chakravyuh.realdata import registry  # noqa: E402
from chakravyuh.realdata.validate import validate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_id", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--near-dup-threshold", type=float, default=0.8)
    a = ap.parse_args()
    ids = a.dataset_id or [i for i in registry.all_ids()
                           if a.all and registry.raw_dir(registry.load(i)).exists()]
    if not ids:
        ap.error("name dataset ids or pass --all")
    out = registry.DATA / "reports"
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    for i in ids:
        rep = validate(i, a.near_dup_threshold)
        (out / f"{i}.validation.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
        c = rep["checks"]
        d = c.get("duplicates", {})
        print(f"\n{i}: {'FAIL' if rep['hard_failures'] else 'ok'}  records={c.get('records', '-')} "
              f"labels={c.get('labels', '-')} unique={d.get('unique_after_normalisation', '-')} "
              f"near-clusters={d.get('near_duplicate_clusters', '-')}")
        for f in rep["hard_failures"]:
            print(f"   FAIL {f}")
        for w in rep["warnings"]:
            print(f"   warn {w}")
        failed |= bool(rep["hard_failures"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
