"""ScamSeq: a small causal transformer over session events.

Heads (per event, using only events up to that point):
    p_scam      probability the session is a scam so far
    next_stage  distribution over the next kill-chain stage (lets us warn before the ask)
    tau         log seconds until the first main payment (when to alert)

Loss: focal BCE (with early-detection weighting) + next-stage CE + tau L1.
About 0.4M parameters; runs in a few milliseconds on CPU.
"""

from __future__ import annotations

import math
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .features import N_ATTRS, N_STAGES, N_TYPES, pad_batch


class TimeEncoding(nn.Module):
    def __init__(self, d: int) -> None:
        super().__init__()
        self.register_buffer("freq", torch.exp(torch.arange(0, d, 2).float() * (-math.log(10000.0) / d)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:          # x: (B, L) log gaps
        ang = x.unsqueeze(-1) * self.freq * 4.0
        return torch.cat([torch.sin(ang), torch.cos(ang)], dim=-1)


class ScamSeq(nn.Module):
    def __init__(self, d: int = 96, layers: int = 3, heads: int = 4, max_len: int = 64) -> None:
        super().__init__()
        self.type_emb = nn.Embedding(N_TYPES, d)
        self.attr_proj = nn.Linear(N_ATTRS, d)
        self.time_enc = TimeEncoding(d)
        self.pos = nn.Embedding(max_len, d)
        layer = nn.TransformerEncoderLayer(d, heads, dim_feedforward=2 * d, dropout=0.1,
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.scam_head = nn.Linear(d, 1)
        self.stage_head = nn.Linear(d, N_STAGES)
        self.tau_head = nn.Linear(d, 1)

    def forward(self, types, attrs, dts, mask):
        B, L = types.shape
        pos = torch.arange(L, device=types.device).clamp(max=self.pos.num_embeddings - 1)
        x = self.type_emb(types) + self.attr_proj(attrs) + self.time_enc(dts) + self.pos(pos)
        causal = torch.triu(torch.ones(L, L, dtype=torch.bool, device=types.device), diagonal=1)
        h = self.encoder(x, mask=causal, src_key_padding_mask=~mask)
        h = self.norm(h)
        return {
            "logit": self.scam_head(h).squeeze(-1),
            "stage_logits": self.stage_head(h),
            "tau": F.softplus(self.tau_head(h).squeeze(-1)),
            "hidden": h,
        }


def _tensors(batch: dict) -> dict:
    return {k: torch.from_numpy(v) for k, v in batch.items()}


def focal_bce(logits, target, gamma: float = 2.0, alpha: float = 0.5):
    p = torch.sigmoid(logits)
    pt = torch.where(target > 0.5, p, 1 - p)
    a = torch.where(target > 0.5, torch.full_like(p, alpha), torch.full_like(p, 1 - alpha))
    return -a * (1 - pt).pow(gamma) * torch.log(pt.clamp_min(1e-6))


def train_scamseq(encoded: list[dict], epochs: int = 12, batch_size: int = 64, lr: float = 2e-3,
                  seed: int = 0, kappa: float = 1.0, log=print, model: ScamSeq | None = None) -> ScamSeq:
    torch.manual_seed(seed)
    rng = random.Random(seed)
    model = model or ScamSeq()
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    steps = epochs * math.ceil(len(encoded) / batch_size)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps)
    for ep in range(epochs):
        model.train()
        idx = list(range(len(encoded)))
        rng.shuffle(idx)
        total = 0.0
        for i in range(0, len(idx), batch_size):
            b = _tensors(pad_batch([encoded[j] for j in idx[i:i + batch_size]]))
            out = model(b["types"], b["attrs"], b["dts"], b["mask"])
            m = b["mask"].float()
            L = m.shape[1]
            target = b["label"].unsqueeze(1).expand_as(out["logit"])
            # Early-detection weight w_t = 1 + kappa * (1 - t/T): knowing early is rewarded.
            lengths = m.sum(1, keepdim=True).clamp_min(1)
            pos = torch.arange(L).unsqueeze(0).float()
            w = (1 + kappa * (1 - pos / lengths)).clamp_min(1.0) * m * b["train_mask"].float()
            l_scam = (focal_bce(out["logit"], target) * w).sum() / w.sum()
            l_stage = F.cross_entropy(out["stage_logits"].reshape(-1, N_STAGES), b["next_stage"].reshape(-1),
                                      ignore_index=-100)
            tm = (b["tau"] >= 0) & b["mask"]
            l_tau = (out["tau"][tm] - b["tau"][tm]).abs().mean() if tm.any() else torch.tensor(0.0)
            loss = l_scam + 0.5 * l_stage + 0.05 * l_tau
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            total += loss.item()
        log(f"  scamseq epoch {ep + 1}/{epochs} loss={total / math.ceil(len(idx) / batch_size):.4f}")
    model.eval()
    return model


def finetune(model: ScamSeq, encoded: list[dict], epochs: int = 3, lr: float = 5e-4, log=print) -> ScamSeq:
    """Continue training an existing model on new sessions (used by the arena's defender turn)."""
    return train_scamseq(encoded, epochs=epochs, lr=lr, model=model, log=log)


@torch.no_grad()
def predict(model: ScamSeq, encoded: list[dict], batch_size: int = 256) -> list[dict]:
    """Per-event outputs for each session: p_scam[t], next-stage probs[t], tau[t], embedding."""
    model.eval()
    results = []
    for i in range(0, len(encoded), batch_size):
        items = encoded[i:i + batch_size]
        b = _tensors(pad_batch(items))
        out = model(b["types"], b["attrs"], b["dts"], b["mask"])
        p = torch.sigmoid(out["logit"]).numpy()
        st = torch.softmax(out["stage_logits"], -1).numpy()
        tau = out["tau"].numpy()
        hid = out["hidden"]
        m = b["mask"].unsqueeze(-1).float()
        emb = ((hid * m).sum(1) / m.sum(1).clamp_min(1)).numpy()
        for j, it in enumerate(items):
            n = it["n"]
            results.append({"p": p[j, :n], "next_stage": st[j, :n], "tau": tau[j, :n], "embedding": emb[j]})
    return results


def save(model: ScamSeq, path: str) -> None:
    torch.save(model.state_dict(), path)


def load(path: str) -> ScamSeq:
    m = ScamSeq()
    m.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    m.eval()
    return m


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


__all__ = ["ScamSeq", "train_scamseq", "predict", "save", "load", "n_params", "np"]
