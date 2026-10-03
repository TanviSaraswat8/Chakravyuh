#!/usr/bin/env python3
"""Measure duplication and leakage across the real message datasets on disk.

    python scripts/leakage_audit.py            # writes data/reports/leakage_audit.json

Reads raw data through the adapters; never modifies it. Numbers feed docs/DATA_LEAKAGE_AUDIT.md.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chakravyuh.realdata import leakage, registry  # noqa: E402
from chakravyuh.realdata.adapters import ADAPTERS  # noqa: E402
from chakravyuh.realdata.dedup import near_dup_clusters  # noqa: E402
from chakravyuh.realdata.languages import language_report  # noqa: E402


def main() -> int:
    t0 = time.time()
    data = {}
    for i in ADAPTERS:
        m = registry.load(i)
        raw = registry.raw_dir(m)
        if raw.exists() and any(raw.iterdir()):
            data[i] = list(ADAPTERS[i](raw))
    rep: dict = {"datasets": {k: len(v) for k, v in data.items()}, "within": {}, "splits": {}}
    clusters = {}
    for name, recs in data.items():
        cl = near_dup_clusters([r["text"] for r in recs])
        clusters[name] = cl
        sizes = Counter(cl)
        rep["within"][name] = {
            "records": len(recs), "near_dup_clusters": len(sizes),
            "largest_cluster": max(sizes.values()) if sizes else 0,
            "records_in_top_10_clusters": sum(c for _, c in sizes.most_common(10)),
            "random_80_20_split_leakage": leakage.random_split_leakage(recs, cl),
            "languages": language_report(recs),
        }
    imc = data.get("imc25_smishing")
    if imc:
        cl = clusters["imc25_smishing"]
        rep["splits"]["imc25_family_spanning_clusters"] = leakage.cross_group_leakage(imc, cl, "scam_type")
        rep["splits"]["imc25_country_spanning_clusters"] = leakage.cross_group_leakage(imc, cl, "country")
        rep["splits"]["imc25_family_counts"] = dict(Counter(r["scam_type"] for r in imc))
        gs = leakage.group_split(imc, cl)
        rep["splits"]["imc25_group_split_counts"] = dict(Counter(gs))
    sp = data.get("sp24_gateway_phishing")
    if sp:
        cl = clusters["sp24_gateway_phishing"]
        ts = sorted(r["timestamp"] for r in sp if r["timestamp"])
        cut = ts[int(len(ts) * 0.8)]
        vcut = ts[int(len(ts) * 0.7)]
        t = leakage.temporal_split(sp, cl, cut, vcut)
        t.pop("assignment")
        rep["splits"]["sp24_temporal"] = {"time_range": [ts[0], ts[-1]], "val_cut": vcut, "test_cut": cut, **t}
    rep["cross_dataset"] = leakage.cross_overlap(data)
    rep["seconds"] = round(time.time() - t0, 1)
    out = registry.DATA / "reports" / "leakage_audit.json"
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: rep[k] for k in ("datasets", "splits", "seconds")}, indent=1))
    for k, v in rep["within"].items():
        print(k, {x: v[x] for x in ("records", "near_dup_clusters", "largest_cluster")},
              "random-split leakage", v["random_80_20_split_leakage"]["share"])
    for k, v in rep["cross_dataset"].items():
        if v["near_dup_share_of_a_records"] >= 0.01:
            print(f"  {k}: near-dup {v['near_dup_share_of_a_records']:.1%}, exact {v['exact_share_of_a_unique_texts']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
