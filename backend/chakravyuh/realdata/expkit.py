"""Shared machinery for the real-data experiments (E0-E4): data access, text variants, models,
metrics, latency and artifact provenance. Real public data only; nothing here touches simulator data."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import platform
import random
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import registry
from .dedup import near_dup_clusters

OUT = registry.REPO / "experiments" / "real"
ART = OUT / "artifacts"
SEED = 13
PLACEHOLDER = re.compile(r"<(?:URL|NUM|MASK|EMAIL|VPA)>")


def seed_all(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
    except ImportError:
        pass


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def git_commit() -> str:
    return subprocess.run(["git", "-C", str(registry.REPO), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def environment() -> dict:
    import sklearn
    import torch
    cpu = ""
    try:
        cpu = next(ln.split(":", 1)[1].strip() for ln in open("/proc/cpuinfo") if ln.startswith("model name"))
    except (OSError, StopIteration):
        pass
    mem = ""
    try:
        mem = next(ln.split(":", 1)[1].strip() for ln in open("/proc/meminfo") if ln.startswith("MemTotal"))
    except (OSError, StopIteration):
        pass
    return {"cpu": cpu, "cpus": os.cpu_count(), "memory": mem, "gpu": "none", "python": platform.python_version(),
            "numpy": np.__version__, "sklearn": sklearn.__version__, "torch": torch.__version__,
            "torch_threads": torch.get_num_threads(), "code_commit": git_commit()}


# ------------------------------------------------------------------------------------------- data
def processed_path(dataset_id: str) -> Path:
    return registry.DATA / "processed" / f"{dataset_id}.msg-v1.jsonl"


def split_path(split_id: str) -> Path:
    return registry.DATA / "splits" / f"{split_id}.json"


def load_records(dataset_id: str) -> list[dict]:
    return [json.loads(x) for x in open(processed_path(dataset_id), encoding="utf-8")]


def load_split(split_id: str) -> dict[str, str]:
    return json.loads(split_path(split_id).read_text())["assignment"]


def data_provenance(datasets: list[str], splits: list[str]) -> dict:
    out = {"datasets": {}, "splits": {}}
    for d in datasets:
        m = registry.load(d)
        out["datasets"][d] = {"version": m.get("version"), "license": m.get("license"),
                              "raw_sha256": m.get("sha256"), "processed_file": processed_path(d).name,
                              "processed_sha256": sha_file(processed_path(d)),
                              "real_or_synthetic": m.get("real_or_synthetic")}
    for s in splits:
        out["splits"][s] = {"file": split_path(s).name, "sha256": sha_file(split_path(s))}
    return out


def stripped(text_masked: str) -> str:
    """Mitigation variant: every placeholder token removed, so masking style can't identify a source."""
    return re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", text_masked)).strip()


EXPORT_ARTEFACT = re.compile(r"(?i)\b(?:image|video|audio|sticker|gif|document|contact card) omitted\b|<media omitted>")


def is_export_artefact(rec: dict) -> bool:
    """Chat-export placeholders (e.g. '?image omitted') are not SMS text; excluded from experiments."""
    return bool(EXPORT_ARTEFACT.search(rec["text"] or ""))


def clean(rec: dict) -> str:
    """Mitigation variant 2: repair mojibake (ftfy), apply the shared masking, strip placeholders."""
    from .textnorm import masked
    try:
        import ftfy
        text = ftfy.fix_text(rec["text"] or "")
    except ImportError:                       # requirements-data.txt lists ftfy
        text = rec["text"] or ""
    return stripped(masked(text))


def variant(rec: dict, name: str) -> str:
    if name == "clean":
        return clean(rec)
    if name == "raw":
        return rec["text"]
    if name == "masked":
        return rec["text_masked"]
    if name == "stripped":
        return stripped(rec["text_masked"])
    raise ValueError(name)


def purge_test_near_dups(train_texts: list[str], test_texts: list[str]) -> list[bool]:
    """True for each test text that is NOT a near-duplicate of any training text."""
    cl = near_dup_clusters(train_texts + test_texts)
    train_cl = set(cl[: len(train_texts)])
    return [c not in train_cl for c in cl[len(train_texts):]]


# --------------------------------------------------------------------------------------- metrics
def ece_top_label(proba: np.ndarray, y_idx: np.ndarray, bins: int = 10) -> float:
    conf = proba.max(1)
    correct = (proba.argmax(1) == y_idx).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1]), 0, bins - 1)
    return float(sum((idx == b).mean() * abs(correct[idx == b].mean() - conf[idx == b].mean())
                     for b in range(bins) if (idx == b).any()))


def confusion(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    c = Counter(zip(y_true, y_pred))
    return {"labels": labels, "matrix": [[c[(a, b)] for b in labels] for a in labels],
            "rows": "true", "cols": "predicted"}


def bootstrap_rate(flags: np.ndarray, n: int = 2000, seed: int = SEED) -> list[float] | None:
    """95% percentile bootstrap CI of a proportion."""
    if len(flags) == 0:
        return None
    rng = np.random.default_rng(seed)
    s = rng.integers(0, len(flags), size=(n, len(flags)))
    m = flags[s].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def latency_ms(predict_one, texts: list[str], n: int = 300) -> dict:
    rng = random.Random(SEED)
    sample = rng.sample(texts, min(n, len(texts)))
    for t in sample[:10]:
        predict_one(t)                          # warm-up
    ts = []
    for t in sample:
        t0 = time.perf_counter()
        predict_one(t)
        ts.append((time.perf_counter() - t0) * 1000)
    a = np.array(ts)
    return {"p50_ms": round(float(np.percentile(a, 50)), 3), "p95_ms": round(float(np.percentile(a, 95)), 3),
            "n": len(a), "mode": "one message per call, CPU, includes feature extraction"}


# ------------------------------------------------------------------------------------- provenance
def save_artifact(obj, exp: str, name: str, meta: dict) -> dict:
    """Pickle a trained model under experiments/real/artifacts (git-ignored) and write its manifest
    (committed). These pickles are local experiment outputs; the API never loads them."""
    ART.mkdir(parents=True, exist_ok=True)
    (OUT / "manifests").mkdir(parents=True, exist_ok=True)
    path = ART / f"{exp}__{name}.pkl"
    with open(path, "wb") as f:
        pickle.dump(obj, f)
    man = {"artifact": str(path.relative_to(registry.REPO)), "sha256": sha_file(path), "bytes": path.stat().st_size,
           "experiment": exp, "model": name, "track": "REAL PUBLIC DATA", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "code_commit": git_commit(), **meta}
    (OUT / "manifests" / f"{exp}__{name}.json").write_text(json.dumps(man, indent=2, default=str) + "\n")
    return {"artifact_sha256": man["sha256"], "manifest": f"experiments/real/manifests/{exp}__{name}.json"}


def write_result(exp: str, result: dict) -> Path:
    (OUT / "results").mkdir(parents=True, exist_ok=True)
    p = OUT / "results" / f"{exp}.json"
    p.write_text(json.dumps(result, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)) + "\n")
    return p
