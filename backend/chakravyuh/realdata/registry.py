"""Dataset registry: one JSON manifest per dataset in data/registry/<dataset_id>.json.

The manifest is the single source of truth for provenance, licence, access status and the SHA-256 of
every raw file. Raw files live in data/real/<data_type>/<dataset_id>/raw/ and are never modified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data"
REGISTRY = DATA / "registry"

# Required by docs/REAL_DATA_STRATEGY.md (governance fields) — every manifest must carry all of them.
REQUIRED_FIELDS = [
    "dataset_id", "name", "source", "official_url", "paper", "license", "version", "download_date",
    "sha256", "sample_count", "schema", "label_schema", "geography", "language", "collection_period",
    "collection_method", "real_or_synthetic", "pii_status", "preprocessing_version", "provenance",
    "limitations",
    # governance extras
    "data_type", "access_status", "license_status", "original_or_mirror", "fetch", "adapter",
    "components", "training_allowed",
]
ACCESS = {"AVAILABLE_NOW", "GITHUB_MIRROR_AVAILABLE", "REQUIRES_LOCAL_DOWNLOAD", "BLOCKED", "REJECTED"}
LICENSE_STATUS = {"CLEAR", "NON_COMMERCIAL", "RESTRICTED", "UNRESOLVED", "CONFLICTING", "NOT_APPLICABLE"}
REAL = {"REAL", "SYNTHETIC", "LLM_GENERATED", "AGGREGATE_REPORTS", "MIXED"}
DATA_TYPES = {"messages", "transactions", "graphs", "campaigns", "complaints", "dialogues", "simulator", "evolution"}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_problems(m: dict) -> list[str]:
    p = [f"missing field: {f}" for f in REQUIRED_FIELDS if f not in m]
    if m.get("access_status") not in ACCESS:
        p.append(f"access_status must be one of {sorted(ACCESS)}")
    if m.get("license_status") not in LICENSE_STATUS:
        p.append(f"license_status must be one of {sorted(LICENSE_STATUS)}")
    if m.get("real_or_synthetic") not in REAL:
        p.append(f"real_or_synthetic must be one of {sorted(REAL)}")
    if m.get("data_type") not in DATA_TYPES:
        p.append(f"data_type must be one of {sorted(DATA_TYPES)}")
    if m.get("training_allowed") and m.get("license_status") in ("UNRESOLVED", "CONFLICTING"):
        p.append("training_allowed cannot be true while the licence is unresolved or conflicting")
    if m.get("training_allowed") and m.get("real_or_synthetic") != "REAL" and m.get("data_type") != "simulator":
        p.append("non-real datasets may only be used on the synthetic track (training_allowed must be false here)")
    return p


def load(dataset_id: str) -> dict:
    return json.loads((REGISTRY / f"{dataset_id}.json").read_text(encoding="utf-8"))


def all_ids() -> list[str]:
    return sorted(p.stem for p in REGISTRY.glob("*.json"))


def raw_dir(m: dict) -> Path:
    return DATA / "real" / m["data_type"] / m["dataset_id"] / "raw"


def save(m: dict) -> None:
    (REGISTRY / f"{m['dataset_id']}.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")
