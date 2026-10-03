"""Leakage auditing and leakage-safe split construction for real message datasets.

Measures (never modifies data):
  * exact / near-duplicate / template overlap inside a dataset and between datasets
  * how much a naive random split leaks (test records with a near-duplicate in train)
  * temporal leakage (later records whose near-duplicate appeared earlier)
Splits:
  * group_split: whole near-duplicate clusters go to one side (no cluster spans train and test)
  * temporal_split: by timestamp, then test records whose cluster appears in train are marked
    'seen_campaign' so known-campaign and novel-campaign results are reported separately
  * holdout_split: one value of a field (scam family, source dataset) held out entirely
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from .dedup import near_dup_clusters
from .textnorm import dedup_key, template_key


def cross_overlap(datasets: dict[str, list[dict]], threshold: float = 0.8) -> dict:
    names = list(datasets)
    texts, owner = [], []
    for n in names:
        for r in datasets[n]:
            texts.append(r["text"])
            owner.append(n)
    clusters = near_dup_clusters(texts, threshold)
    members: dict[int, set] = defaultdict(set)
    for c, o in zip(clusters, owner):
        members[c].add(o)
    keys = {n: {dedup_key(r["text"]) for r in datasets[n]} for n in names}
    tkeys = {n: {template_key(r["text"]) for r in datasets[n]} for n in names}
    out = {}
    for a in names:
        ia = [i for i, o in enumerate(owner) if o == a]
        for b in names:
            if a == b:
                continue
            near = sum(1 for i in ia if b in members[clusters[i]])
            out[f"{a} -> {b}"] = {
                "exact_share_of_a_unique_texts": round(len(keys[a] & keys[b]) / max(len(keys[a]), 1), 4),
                "template_share_of_a_templates": round(len(tkeys[a] & tkeys[b]) / max(len(tkeys[a]), 1), 4),
                "near_dup_share_of_a_records": round(near / max(len(ia), 1), 4),
            }
    return out


def random_split_leakage(recs: list[dict], clusters: list[int], test_frac: float = 0.2, seed: int = 0) -> dict:
    idx = list(range(len(recs)))
    random.Random(seed).shuffle(idx)
    cut = int(len(idx) * (1 - test_frac))
    train_clusters = {clusters[i] for i in idx[:cut]}
    test = idx[cut:]
    leaked = sum(1 for i in test if clusters[i] in train_clusters)
    return {"test_records": len(test), "test_with_near_dup_in_train": leaked,
            "share": round(leaked / max(len(test), 1), 4)}


def group_split(recs: list[dict], clusters: list[int], test_frac: float = 0.2, val_frac: float = 0.1,
                seed: int = 0) -> list[str]:
    """Assign whole clusters to train/val/test so no near-duplicate crosses the boundary."""
    ids = sorted(set(clusters))
    random.Random(seed).shuffle(ids)
    sizes = Counter(clusters)
    total, acc, side = len(recs), 0, {}
    for c in ids:
        frac = acc / total
        side[c] = "test" if frac < test_frac else ("val" if frac < test_frac + val_frac else "train")
        acc += sizes[c]
    return [side[c] for c in clusters]


def temporal_split(recs: list[dict], clusters: list[int], cut_iso: str, val_cut_iso: str | None = None) -> dict:
    """Records before val_cut -> train, [val_cut, cut) -> val, >= cut -> test. Records without a
    usable timestamp are excluded (listed as 'no_time')."""
    out, seen = [], set()
    order = sorted(range(len(recs)), key=lambda i: recs[i].get("timestamp") or "")
    for i in order:
        ts = recs[i].get("timestamp")
        if not ts or recs[i].get("timestamp_quality") not in ("unix_seconds", "report_time"):
            out.append((i, "no_time"))
            continue
        s = "test" if ts >= cut_iso else ("val" if val_cut_iso and ts >= val_cut_iso else "train")
        out.append((i, s))
    train_clusters = {clusters[i] for i, s in out if s == "train"}
    sides = dict(out)
    test = [i for i, s in out if s == "test"]
    seen = sum(1 for i in test if clusters[i] in train_clusters)
    return {"assignment": [sides[i] for i in range(len(recs))],
            "counts": dict(Counter(sides.values())),
            "test_seen_campaign": seen, "test_novel_campaign": len(test) - seen,
            "seen_share": round(seen / max(len(test), 1), 4)}


def holdout_split(recs: list[dict], field: str, held_out: str) -> dict:
    side = ["test" if (r.get(field) or "") == held_out else "train" for r in recs]
    return {"assignment": side, "counts": dict(Counter(side))}


def cross_group_leakage(recs: list[dict], clusters: list[int], field: str) -> dict:
    """How many near-duplicate clusters span more than one value of `field` (e.g. scam_type)."""
    vals: dict[int, set] = defaultdict(set)
    for r, c in zip(recs, clusters):
        vals[c].add(r.get(field))
    spanning = [c for c, v in vals.items() if len(v) > 1]
    n_rec = sum(1 for c in clusters if c in set(spanning))
    return {"clusters_spanning_values": len(spanning), "records_in_spanning_clusters": n_rec,
            "share": round(n_rec / max(len(recs), 1), 4)}
