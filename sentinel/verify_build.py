"""Check that a local Sentinel build is byte-identical to the approved, committed build manifest.

    python sentinel/verify_build.py sentinel_real_v2_clean

Exit 1 on any difference: training must use exactly the corpus that was reviewed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    name = sys.argv[1]
    frozen = json.loads((ROOT / "sentinel" / "manifests" / f"{name}.build.json").read_text())
    out = ROOT / "sentinel" / "sft_real" / name
    ok = hashlib.sha256((ROOT / frozen["config_file"]).read_bytes()).hexdigest() == frozen["config_sha256"]
    print(f"  {'ok  ' if ok else 'FAIL'} config {frozen['config_file']}")
    for f, meta in frozen["outputs"].items():
        p = out / f
        good = p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == meta["sha256"]
        ok &= good
        print(f"  {'ok  ' if good else 'FAIL'} {f} ({meta['rows']} rows)")
    print("BUILD MATCHES APPROVED MANIFEST" if ok else "BUILD DIFFERS: do not train on it")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
