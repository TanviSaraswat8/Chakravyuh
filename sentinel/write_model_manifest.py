"""Record exactly what a trained Sentinel is: base model, config, data hashes, adapter hashes, metrics.

    python sentinel/write_model_manifest.py --run sentinel/outputs/sentinel_real_v1 \
        --data sentinel/sft_real/sentinel_real_v1 --config sentinel/configs/sentinel_real_v1.json

Writes <run>/MODEL_MANIFEST.json. Without metrics_real.json the manifest says status=UNEVALUATED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    run, data = Path(a.run), Path(a.data)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    metrics = run / "metrics_real.json"
    m = {"model": "sentinel", "track": "REAL", "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
         "code_commit": commit, "config": json.loads(Path(a.config).read_text()),
         "data_build_manifest": json.loads((data / "build_manifest.json").read_text()),
         "adapter_files": {str(p.relative_to(run)): sha(p) for p in sorted(run.rglob("*"))
                           if p.is_file() and p.suffix in (".safetensors", ".bin", ".gguf", ".json")
                           and "predictions" not in p.parts and p.name != "MODEL_MANIFEST.json"},
         "metrics_file": str(metrics) if metrics.exists() else None,
         "status": "EVALUATED" if metrics.exists() else "UNEVALUATED",
         "claims_allowed": "Only the numbers in metrics_real.json, on the named test files. Not real-world deployment performance."}
    (run / "MODEL_MANIFEST.json").write_text(json.dumps(m, indent=2) + "\n")
    print(f"wrote {run / 'MODEL_MANIFEST.json'} ({m['status']})")


if __name__ == "__main__":
    main()
