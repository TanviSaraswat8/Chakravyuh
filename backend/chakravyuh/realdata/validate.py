"""Dataset validation. Reads raw files and the manifest; never writes to raw data.

Checks: manifest completeness, licence status, SHA-256 of every raw file, encoding, malformed rows,
schema/required fields, missingness, duplicate rows, exact and near-duplicate messages, label validity,
PII indicators. Hard failures make the dataset unusable until fixed; warnings are reported.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

from . import registry
from .adapters import ADAPTERS, LABELS
from .dedup import exact_groups, near_dup_clusters
from .pii import indicators

REQUIRED_RECORD_FIELDS = ["record_id", "dataset_id", "text", "label"]


def _encoding_report(path: Path) -> dict:
    if path.suffix.lower() in (".zip", ".gz", ".xls", ".parquet"):
        return {"utf8_valid": None, "note": "binary container; text encoding checked by the adapter"}
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
        return {"utf8_valid": True, "bom": raw.startswith(b"\xef\xbb\xbf")}
    except UnicodeDecodeError as e:
        bad = raw.decode("utf-8", errors="replace").count("�")
        return {"utf8_valid": False, "first_error_byte": e.start, "replacement_chars_if_utf8": bad}


def _field_counts(path: Path) -> dict:
    if path.suffix.lower() not in (".csv", ".tsv"):
        return {}
    text = path.read_bytes().decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t" if path.suffix == ".tsv" else ","))
    if not rows:
        return {"rows": 0}
    counts = Counter(len(r) for r in rows[1:])
    expected = len(rows[0])
    return {"header_fields": expected, "row_field_counts": dict(counts.most_common(5)),
            "rows_not_matching_header": sum(v for k, v in counts.items() if k != expected)}


def validate(dataset_id: str, near_dup_threshold: float = 0.8) -> dict:
    m = registry.load(dataset_id)
    rep: dict = {"dataset_id": dataset_id, "hard_failures": [], "warnings": [], "checks": {}}
    fail, warn = rep["hard_failures"].append, rep["warnings"].append

    problems = registry.manifest_problems(m)
    rep["checks"]["manifest"] = {"problems": problems}
    for p in problems:
        fail(f"manifest: {p}")
    rep["checks"]["license"] = {"license": m.get("license"), "status": m.get("license_status")}
    if m.get("license_status") in ("UNRESOLVED", "CONFLICTING"):
        warn(f"licence {m.get('license_status')}: not ingested for training")

    raw = registry.raw_dir(m)
    prov_file = raw / ".provenance.json"
    prov = json.loads(prov_file.read_text()) if prov_file.exists() else {}
    rep["checks"]["provenance"] = prov
    expected = m.get("sha256") or {}
    if prov.get("kind") == "mirror":
        expected = m.get("mirror_sha256") or {}
        warn("raw files are a third-party mirror copy (audit only); the official release is not verified")
    files = {}
    for name, digest in expected.items():
        p = raw / name
        if not p.exists():
            fail(f"raw file missing: {p.relative_to(registry.REPO)}")
            continue
        actual = registry.sha256_file(p)
        files[name] = {"bytes": p.stat().st_size, "sha256_ok": actual == digest, "encoding": _encoding_report(p),
                       "structure": _field_counts(p)}
        if actual != digest:
            fail(f"SHA-256 mismatch for {name}: expected {digest[:12]}..., got {actual[:12]}...")
        enc = files[name]["encoding"]
        if enc.get("utf8_valid") is False:
            warn(f"{name} is not valid UTF-8 (decoded with a fallback encoding)")
        if files[name]["structure"].get("rows_not_matching_header"):
            warn(f"{name}: {files[name]['structure']['rows_not_matching_header']} rows don't match the header's "
                 f"field count (header {files[name]['structure']['header_fields']})")
    rep["checks"]["files"] = files
    if not expected:
        fail("no raw files registered (sha256 empty): acquire and register the data first")
    if rep["hard_failures"] or dataset_id not in ADAPTERS:
        if dataset_id not in ADAPTERS:
            warn("no message adapter: record-level checks skipped")
        return rep

    recs = list(ADAPTERS[dataset_id](raw))
    n = len(recs)
    rep["checks"]["records"] = n
    if n != m.get("sample_count"):
        warn(f"adapter produced {n} records; manifest sample_count is {m.get('sample_count')}")
    missing_fields = Counter(f for r in recs for f in REQUIRED_RECORD_FIELDS if r.get(f) in (None, ""))
    rep["checks"]["missingness"] = {
        f: round(sum(1 for r in recs if r.get(f) in (None, "", [])) / max(n, 1), 4)
        for f in ("text", "label", "language", "country", "timestamp", "year", "scam_type", "sender_type")}
    if missing_fields.get("text"):
        warn(f"{missing_fields['text']} records have empty text")
    labels = Counter(r["label"] for r in recs)
    rep["checks"]["labels"] = dict(labels)
    invalid = [lab for lab in labels if lab not in LABELS]
    if invalid:
        fail(f"invalid labels {invalid}")
    if labels.get("unknown"):
        warn(f"{labels['unknown']} records have no usable label")

    texts = [r["text"] for r in recs]
    rows_seen = Counter(tuple(sorted((k, str(v)) for k, v in r.items() if k not in ("record_id", "source_row")))
                        for r in recs)
    exact = exact_groups(texts)
    near = near_dup_clusters(texts, near_dup_threshold)
    conflicting = sum(1 for g, labs in _labels_by_group(exact, recs).items() if len(labs - {"unknown"}) > 1)
    rep["checks"]["duplicates"] = {
        "duplicate_rows": sum(c - 1 for c in rows_seen.values() if c > 1),
        "exact_duplicate_texts_raw": n - len(set(texts)),
        "unique_after_normalisation": len(set(exact)),
        "near_duplicate_clusters": len(set(near)),
        "records_in_multi_member_near_clusters": sum(c for c in Counter(near).values() if c > 1),
        "groups_with_conflicting_labels": conflicting,
        "near_dup_threshold": near_dup_threshold,
    }
    if conflicting:
        warn(f"{conflicting} duplicate groups carry conflicting labels")
    pii = Counter(k for t in texts for k in indicators(t))
    rep["checks"]["pii_indicators"] = {k: {"records": v, "share": round(v / max(n, 1), 4)}
                                       for k, v in pii.most_common()}
    for k in ("aadhaar_like", "payment_card_luhn", "pan_like"):
        if pii.get(k):
            warn(f"{pii[k]} records match {k} (heuristic); review before any redistribution")
    return rep


def _labels_by_group(groups: list[int], recs: list[dict]) -> dict[int, set]:
    out: dict[int, set] = {}
    for g, r in zip(groups, recs):
        out.setdefault(g, set()).add(r["label"])
    return out
