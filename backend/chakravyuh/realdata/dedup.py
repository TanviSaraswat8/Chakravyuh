"""Exact and near-duplicate detection (MinHash + LSH on character 5-gram shingles).

Near-duplicate clustering is approximate: candidates come from LSH buckets (8 bands x 8 rows of a
64-permutation MinHash, ~0.77 Jaccard knee) and are joined to the bucket's first member when their
estimated Jaccard is >= threshold (single-linkage through union-find). Exact duplicates (same
dedup_key) are collapsed first, so large template floods stay cheap.
"""

from __future__ import annotations

import zlib
from collections import defaultdict

import numpy as np

from .textnorm import dedup_key, shingles

N_PERM, BANDS, ROWS = 64, 8, 8
_P = np.int64(2_147_483_647)
_rng = np.random.default_rng(20261003)
_A = _rng.integers(1, _P, size=N_PERM, dtype=np.int64)
_B = _rng.integers(0, _P, size=N_PERM, dtype=np.int64)


def signature(text: str) -> np.ndarray:
    sh = shingles(text)
    if not sh:
        return np.full(N_PERM, _P, dtype=np.int64)
    x = np.fromiter((zlib.crc32(s.encode("utf-8")) & 0x7FFFFFFF for s in sh), dtype=np.int64)
    return ((_A[:, None] * x[None, :] + _B[:, None]) % _P).min(axis=1)


class UnionFind:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def exact_groups(texts: list[str]) -> list[int]:
    """Group id per text: equal dedup_key -> same id."""
    seen: dict[str, int] = {}
    return [seen.setdefault(dedup_key(t), len(seen)) for t in texts]


def near_dup_clusters(texts: list[str], threshold: float = 0.8) -> list[int]:
    """Cluster id per text (exact duplicates always share a cluster)."""
    exact = exact_groups(texts)
    n_unique = max(exact) + 1 if exact else 0
    first: dict[int, int] = {}
    for i, g in enumerate(exact):
        first.setdefault(g, i)
    reps = [texts[first[g]] for g in range(n_unique)]
    sigs = np.stack([signature(t) for t in reps]) if reps else np.zeros((0, N_PERM), dtype=np.int64)
    uf = UnionFind(n_unique)
    for b in range(BANDS):
        buckets: dict[bytes, list[int]] = defaultdict(list)
        band = sigs[:, b * ROWS:(b + 1) * ROWS]
        for i in range(n_unique):
            buckets[band[i].tobytes()].append(i)
        for members in buckets.values():
            if len(members) < 2:
                continue
            head = members[0]
            sim = (sigs[members[1:]] == sigs[head]).mean(axis=1)
            for m, s in zip(members[1:], sim):
                if s >= threshold:
                    uf.union(head, m)
    root = [uf.find(g) for g in range(n_unique)]
    return [root[g] for g in exact]
