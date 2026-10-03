#!/usr/bin/env python3
"""Register the OFFICIAL UCI SMS Spam Collection from the zip downloaded from UCI.

    python scripts/register_official_uci.py data/incoming/sms+spam+collection.zip

Records the zip's SHA-256, extracts SMSSpamCollection + readme (path-traversal safe), installs them
read-only as the official raw files (replacing the audit-only mirror copy), pins their SHA-256 and
updates the manifest's provenance, licence and label mapping. Raw files are never committed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from chakravyuh.realdata import registry  # noqa: E402
from fetch_real_datasets import _install  # noqa: E402

OFFICIAL_URL = "https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip"


def main() -> int:
    zpath = Path(sys.argv[1]).expanduser()
    zsha = registry.sha256_file(zpath)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        files = {}
        for n in names:
            base = Path(n).name
            if base not in ("SMSSpamCollection", "readme") or Path(n).is_absolute() or ".." in Path(n).parts:
                continue
            if z.getinfo(n).file_size > 5_000_000:
                raise SystemExit(f"{n} is unexpectedly large")
            out = Path(tmp) / base
            out.write_bytes(z.read(n))
            files[base] = out
        if "SMSSpamCollection" not in files:
            raise SystemExit(f"SMSSpamCollection not in zip (contents: {names})")
        lines = files["SMSSpamCollection"].read_text(encoding="utf-8", errors="replace").splitlines()
        labels = {}
        for ln in lines:
            labels[ln.split("\t", 1)[0]] = labels.get(ln.split("\t", 1)[0], 0) + 1
        m = registry.load("uci_sms_spam")
        m["sha256"] = {}
        now = datetime.now(UTC).isoformat(timespec="seconds")
        _install(m, files, {"kind": "local_download", "from": OFFICIAL_URL, "zip_name": zpath.name,
                            "zip_sha256": zsha, "zip_members": names, "fetched_at": now}, pin=True)
    m = registry.load("uci_sms_spam")
    m.update({
        "access_status": "AVAILABLE_NOW",
        "original_or_mirror": "official UCI download (manual browser download by the project owner; UCI blocked from the build environment)",
        "license": "CC BY 4.0 (stated on the UCI dataset page: 'This dataset is licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) license.')",
        "license_status": "CLEAR",
        "version": f"UCI dataset 228 (donated 2012-06-21), DOI 10.24432/C5CC84; zip sha256 {zsha}",
        "official_download": {"url": OFFICIAL_URL, "zip_sha256": zsha, "zip_members": names, "registered_at": now},
        "sample_count": len([ln for ln in lines if "\t" in ln]),
        "label_schema": {"raw": labels, "canonical": "ham -> legit; spam -> spam (NOT scam: the class mixes premium-rate prize scams and marketing)"},
        "provenance": "Official zip from the UCI Machine Learning Repository; SHA-256 recorded at registration. Citation: Almeida & Hidalgo (2011), SMS Spam Collection, UCI, doi:10.24432/C5CC84.",
        "training_note": "Used ONLY as an independent evaluation source (E5-E7) and for threshold calibration on a held-out half; never as training data for the E3 models.",
    })
    m["fetch"]["files"] = [{"dest": "SMSSpamCollection"}, {"dest": "readme"}]
    registry.save(m)
    same = m.get("sha256", {}).get("SMSSpamCollection") == m.get("mirror_sha256", {}).get("SMSSpamCollection")
    print(json.dumps({"zip_sha256": zsha, "files": m["sha256"], "labels": labels,
                      "official_equals_audited_mirror": same}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
