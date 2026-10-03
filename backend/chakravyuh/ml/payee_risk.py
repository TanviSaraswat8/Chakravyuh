"""Payee and mule risk on the transaction graph.

Two layers:
1. Hand-crafted node features (fan-in from strangers, pass-through ratio, dwell time, account age...).
2. A 2-layer GraphSAGE with time-decay attention over incoming/outgoing edges, written in plain
   PyTorch (no PyG dependency) so it runs anywhere:

   h_v' = ReLU(W [h_v || sum_u alpha_uv h_u]),  alpha_uv = softmax_u(-lambda * (t_now - t_uv))
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

FEATURES = ["log_in_deg", "log_out_deg", "uniq_senders_log", "first_time_in_share", "pass_through_1h",
            "median_dwell_log", "account_age_log", "devices", "in_amount_log", "out_in_ratio"]


def load_graph(ledger_csv: str, accounts_csv: str, today_day: int = 400):
    accounts = {}
    with open(accounts_csv) as f:
        for r in csv.DictReader(f):
            accounts[r["vpa"]] = r
    edges = []
    with open(ledger_csv) as f:
        for r in csv.DictReader(f):
            edges.append((r["src"], r["dst"], float(r["amount"]), float(r["t"]), int(r["first_time"])))
    return accounts, edges


def node_features(accounts: dict, edges: list, today_day: int = 400):
    ids = list(accounts)
    index = {v: i for i, v in enumerate(ids)}
    inc, out = defaultdict(list), defaultdict(list)
    for s, d, amt, t, ft in edges:
        if s in index and d in index:
            out[s].append((d, amt, t))
            inc[d].append((s, amt, t, ft))
    X = np.zeros((len(ids), len(FEATURES)), np.float32)
    for v, i in index.items():
        ins, outs = inc[v], out[v]
        in_amt = sum(a for _, a, _, _ in ins)
        out_amt = sum(a for _, a, _ in outs)
        # pass-through: share of incoming money that leaves within 1 hour
        passed, dwell = 0.0, []
        out_times = sorted(t for _, _, t in outs)
        for _, a, t, _ in ins:
            nxt = next((ot for ot in out_times if ot >= t), None)
            if nxt is not None:
                dwell.append(nxt - t)
                if nxt - t <= 3600:
                    passed += a
        acct = accounts[v]
        X[i] = [
            math.log1p(len(ins)), math.log1p(len(outs)), math.log1p(len({s for s, *_ in ins})),
            (sum(ft for *_, ft in ins) / len(ins)) if ins else 0.0,
            passed / in_amt if in_amt else 0.0,
            math.log1p(float(np.median(dwell))) / 12 if dwell else 1.0,
            math.log1p(today_day - int(acct["created_day"])) / 7,
            float(acct["devices"]) / 6,
            math.log1p(in_amt) / 15,
            min(out_amt / in_amt, 2.0) if in_amt else 0.0,
        ]
    y = np.array([int(accounts[v]["is_mule"]) for v in ids], np.float32)
    return ids, index, X, y, inc, out


def build_adjacency(index: dict, edges: list, lam: float = 1 / (7 * 86400)):
    """Row-normalised neighbour weights with time decay (both edge directions)."""
    t_now = max((t for *_, t, _ in edges), default=0.0)
    rows, cols, vals = [], [], []
    for s, d, _, t, _ in edges:
        if s in index and d in index:
            w = math.exp(-lam * (t_now - t))
            rows += [index[d], index[s]]
            cols += [index[s], index[d]]
            vals += [w, w]
    n = len(index)
    A = torch.sparse_coo_tensor(torch.tensor([rows, cols]), torch.tensor(vals, dtype=torch.float32), (n, n)).coalesce()
    deg = torch.sparse.sum(A, dim=1).to_dense().clamp_min(1e-6)
    i = A.indices()
    A = torch.sparse_coo_tensor(i, A.values() / deg[i[0]], (n, n)).coalesce()
    return A


class SAGE(nn.Module):
    def __init__(self, d_in: int, d: int = 64) -> None:
        super().__init__()
        self.l1 = nn.Linear(2 * d_in, d)
        self.l2 = nn.Linear(2 * d, d)
        self.out = nn.Linear(d, 1)

    def forward(self, X, A):
        h = F.relu(self.l1(torch.cat([X, torch.sparse.mm(A, X)], 1)))
        h = F.dropout(h, 0.2, self.training)
        h = F.relu(self.l2(torch.cat([h, torch.sparse.mm(A, h)], 1)))
        return self.out(h).squeeze(-1)


def train_payee_model(ledger_csv: str, accounts_csv: str, epochs: int = 300, seed: int = 0, log=print):
    torch.manual_seed(seed)
    accounts, edges = load_graph(ledger_csv, accounts_csv)
    ids, index, X, y, *_ = node_features(accounts, edges)
    A = build_adjacency(index, edges)
    Xt, yt = torch.from_numpy(X), torch.from_numpy(y)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ids))
    n_tr = int(0.7 * len(ids))
    tr, te = torch.from_numpy(perm[:n_tr]), torch.from_numpy(perm[n_tr:])
    model = SAGE(X.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)
    pos_w = torch.tensor((1 - y.mean()) / max(y.mean(), 1e-3))
    for _ in range(epochs):
        model.train()
        logits = model(Xt, A)
        loss = F.binary_cross_entropy_with_logits(logits[tr], yt[tr], pos_weight=pos_w)
        opt.zero_grad()
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        p = torch.sigmoid(model(Xt, A)).numpy()
    from sklearn.metrics import average_precision_score, roc_auc_score
    te_np = te.numpy()
    metrics = {"pr_auc": float(average_precision_score(y[te_np], p[te_np])),
               "roc_auc": float(roc_auc_score(y[te_np], p[te_np])), "n_accounts": len(ids),
               "n_mules": int(y.sum())}
    log(f"  payee GNN: test PR-AUC={metrics['pr_auc']:.3f} ROC-AUC={metrics['roc_auc']:.3f}")
    scores = {v: round(float(p[i]), 4) for v, i in index.items()}
    return model, scores, metrics
