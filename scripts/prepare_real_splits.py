#!/usr/bin/env python3
"""Preprocess real message datasets and build leakage-safe splits. No model is trained here.

    python scripts/prepare_real_splits.py

Outputs (git-ignored):
  data/processed/<dataset_id>.msg-v1.jsonl   canonical records + text_masked + cluster ids
  data/splits/<split_id>.json                record_id -> train/val/test (+ seen/novel flags)
  data/splits/SPLITS.json                    what each split is for, sizes, and its leakage controls

Only datasets whose manifest allows training are processed into training splits. Datasets on disk
with unresolved licences are processed for the audit only (flag audit_only=true) and never enter a split.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chakravyuh.realdata import leakage, registry  # noqa: E402
from chakravyuh.realdata.adapters import ADAPTERS, PREPROCESSING_VERSION  # noqa: E402
from chakravyuh.realdata.dedup import exact_groups, near_dup_clusters  # noqa: E402
from chakravyuh.realdata.textnorm import masked  # noqa: E402

SEED = 13
HOLDOUT_FAMILIES = ["delivery", "government"]       # IMC'25 families held out for unseen-family tests


def load(dataset_id: str) -> tuple[dict, list[dict]] | None:
    m = registry.load(dataset_id)
    raw = registry.raw_dir(m)
    if not raw.exists() or not any(raw.iterdir()):
        return None
    prov = json.loads((raw / ".provenance.json").read_text()) if (raw / ".provenance.json").exists() else {}
    recs = list(ADAPTERS[dataset_id](raw))
    cl = near_dup_clusters([r["text"] for r in recs])
    ex = exact_groups([r["text"] for r in recs])
    audit_only = not m["training_allowed"] or prov.get("kind") == "mirror"
    for r, c, e in zip(recs, cl, ex):
        r.update(text_masked=masked(r["text"]), near_dup_cluster=f"{dataset_id}:{c}", exact_group=f"{dataset_id}:{e}",
                 preprocessing_version=PREPROCESSING_VERSION, real_or_synthetic=m["real_or_synthetic"],
                 audit_only=audit_only)
    return m, recs


def write_split(split_id: str, assign: dict[str, str], meta: dict, index: dict) -> None:
    out = registry.DATA / "splits" / f"{split_id}.json"
    out.write_text(json.dumps({"split_id": split_id, **meta, "assignment": assign}) + "\n")
    index[split_id] = {**meta, "counts": dict(Counter(assign.values()))}
    print(f"  {split_id}: {index[split_id]['counts']}")


def main() -> int:
    (registry.DATA / "processed").mkdir(parents=True, exist_ok=True)
    (registry.DATA / "splits").mkdir(parents=True, exist_ok=True)
    loaded = {}
    for i in ADAPTERS:
        got = load(i)
        if got is None:
            print(f"{i}: not on disk, skipped")
            continue
        m, recs = got
        loaded[i] = recs
        path = registry.DATA / "processed" / f"{i}.{PREPROCESSING_VERSION}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{i}: {len(recs)} records -> {path.relative_to(registry.REPO)} (audit_only={recs[0]['audit_only']})")

    index: dict = {}
    imc = [r for r in loaded.get("imc25_smishing", []) if r["label"] != "unknown"]
    if imc and not imc[0]["audit_only"]:
        cl = [r["near_dup_cluster"] for r in imc]
        side = leakage.group_split(imc, cl, test_frac=0.2, val_frac=0.1, seed=SEED)
        write_split("imc25_group_v1", {r["record_id"]: s for r, s in zip(imc, side)},
                    {"purpose": "in-distribution test; whole near-duplicate clusters on one side",
                     "dataset": "imc25_smishing", "real_or_synthetic": "REAL", "control": "near-dup cluster grouping"}, index)
        for fam in HOLDOUT_FAMILIES:
            held_clusters = {r["near_dup_cluster"] for r in imc if r["scam_type"] == fam}
            assign = {}
            for r in imc:
                if r["scam_type"] == fam:
                    assign[r["record_id"]] = "test"
                elif r["near_dup_cluster"] in held_clusters:
                    assign[r["record_id"]] = "purged"      # near-duplicate of a held-out message
                else:
                    assign[r["record_id"]] = "train"
            write_split(f"imc25_holdout_{fam.replace(' ', '_')}_v1", assign,
                        {"purpose": f"unseen scam family '{fam}' (scam-type generalisation)", "dataset": "imc25_smishing",
                         "real_or_synthetic": "REAL", "control": "family held out; near-duplicates of held-out "
                         "messages purged from train"}, index)
    sp = loaded.get("sp24_gateway_phishing", [])
    if sp and not sp[0]["audit_only"]:
        ts = sorted(r["timestamp"] for r in sp if r["timestamp"])
        cut, vcut = ts[int(len(ts) * 0.8)], ts[int(len(ts) * 0.7)]
        t = leakage.temporal_split(sp, [r["near_dup_cluster"] for r in sp], cut, vcut)
        train_cl = {r["near_dup_cluster"] for r, s in zip(sp, t["assignment"]) if s == "train"}
        assign = {}
        for r, s in zip(sp, t["assignment"]):
            if s == "test":
                s = "test_seen_campaign" if r["near_dup_cluster"] in train_cl else "test_novel_campaign"
            assign[r["record_id"]] = s
        write_split("sp24_temporal_v1", assign,
                    {"purpose": "temporal + campaign novelty: is a new campaign caught after training on older ones?",
                     "dataset": "sp24_gateway_phishing", "real_or_synthetic": "REAL", "val_cut": vcut, "test_cut": cut,
                     "control": "time order; test split into seen-campaign and novel-campaign"}, index)
    # Any other licensed, verified dataset (e.g. UCI ham, MOZ after local download): grouped split.
    for i, recs in loaded.items():
        if i in ("imc25_smishing", "sp24_gateway_phishing") or not recs or recs[0]["audit_only"]:
            continue
        recs = [r for r in recs if r["label"] != "unknown"]
        side = leakage.group_split(recs, [r["near_dup_cluster"] for r in recs], seed=SEED)
        write_split(f"{i.replace('_sms_spam', '').replace('_smishing', '')}_group_v1",
                    {r["record_id"]: s for r, s in zip(recs, side)},
                    {"purpose": "grouped split", "dataset": i, "real_or_synthetic": "REAL",
                     "control": "near-dup cluster grouping"}, index)
    (registry.DATA / "splits" / "SPLITS.json").write_text(json.dumps(index, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
