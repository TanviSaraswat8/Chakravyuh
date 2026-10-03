"""Session -> model inputs.

Each event becomes (type id, attribute vector, log time gap). The kill-chain
stage is a training *target*, never an input: at inference nobody tells us
the stage, the models infer it.
"""

from __future__ import annotations

import math

import numpy as np

from ..sim.taxonomy import CHANNELS, EVENT_INDEX, STAGE_INDEX, STAGES, TACTICS

N_TYPES = len(EVENT_INDEX)
N_STAGES = len(STAGES) + 1          # + "end"
END_STAGE = len(STAGES)
ATTR_NAMES = (
    [f"tac_{t}" for t in TACTICS]
    + ["msg_p_scam", "known_sender", "call_unknown", "call_minutes_log", "amount_ratio_log",
       "first_time_payee", "payee_age_log", "recv_amount_log"]
    + [f"ch_{c}" for c in CHANNELS]
)
N_ATTRS = len(ATTR_NAMES)
MAX_LEN = 48


def event_attrs(e: dict, tag: dict | None) -> list[float]:
    a = e.get("attrs", {})
    tactics = (tag or {}).get("tactics", [])
    v = [1.0 if t in tactics else 0.0 for t in TACTICS]
    v.append(float((tag or {}).get("p_scam", 0.0)))
    v.append(1.0 if a.get("known_sender") else 0.0)
    v.append(1.0 if e["type"] == "CALL" and not a.get("known", False) else 0.0)
    v.append(math.log1p(a.get("minutes", 0.0)) / 5)
    v.append(math.log1p(a.get("amount_ratio", 0.0)) / 6)
    v.append(1.0 if a.get("first_time") or e["type"] == "PAYEE_NEW" else 0.0)
    v.append(math.log1p(a.get("payee_age_days", 0.0)) / 7 if e["type"] == "PAYEE_NEW" else 0.0)
    v.append(math.log1p(a.get("amount", 0.0)) / 14 if e["type"] == "RECV" else 0.0)
    v += [1.0 if e.get("channel") == c else 0.0 for c in CHANNELS]
    return v


def encode_session(session: dict, tags: dict[str, dict]) -> dict:
    """Arrays for one session, truncated to the last MAX_LEN events."""
    events = session["events"][-MAX_LEN:]
    types, attrs, dts, stages = [], [], [], []
    prev_t = events[0]["t"] if events else 0.0
    for e in events:
        tag = tags.get(e["text"]) if e["type"] == "MSG_RECV" and e.get("text") else None
        types.append(EVENT_INDEX[e["type"]])
        attrs.append(event_attrs(e, tag))
        dts.append(math.log1p(max(0.0, e["t"] - prev_t)))
        prev_t = e["t"]
        stages.append(STAGE_INDEX.get(e["stage"], 0))
    n = len(events)
    next_stage = stages[1:] + [END_STAGE]
    # Train the scam head only from the first real scam evidence onwards. A disguised opener
    # (a genuine-looking message the attacker borrowed) is not evidence, so it is not labelled scam.
    first_evidence = 0
    if session.get("label", 0) == 1:
        first_evidence = next((i for i, e in enumerate(events) if not e.get("attrs", {}).get("disguise")), n)
    train_mask = [i >= first_evidence for i in range(n)]
    # Seconds until the first completed main payment, for events before it.
    pay_t = next((e["t"] for e in events if e["type"] == "PAY" and e["attrs"].get("amount_ratio", 0) > 1.5
                  and not e["attrs"].get("cancelled")), None)
    tau = [math.log1p(pay_t - e["t"]) if pay_t is not None and e["t"] < pay_t else -1.0 for e in events]
    return {
        "types": np.array(types, dtype=np.int64),
        "attrs": np.array(attrs, dtype=np.float32).reshape(n, N_ATTRS),
        "dts": np.array(dts, dtype=np.float32),
        "stages": np.array(stages, dtype=np.int64),
        "next_stage": np.array(next_stage, dtype=np.int64),
        "tau": np.array(tau, dtype=np.float32),
        "train_mask": np.array(train_mask, dtype=bool),
        "label": int(session.get("label", 0)),
        "n": n,
    }


def pad_batch(items: list[dict]) -> dict:
    L = max(i["n"] for i in items)
    B = len(items)
    out = {
        "types": np.zeros((B, L), np.int64),
        "attrs": np.zeros((B, L, N_ATTRS), np.float32),
        "dts": np.zeros((B, L), np.float32),
        "next_stage": np.full((B, L), -100, np.int64),
        "tau": np.full((B, L), -1.0, np.float32),
        "mask": np.zeros((B, L), bool),
        "train_mask": np.zeros((B, L), bool),
        "label": np.array([i["label"] for i in items], np.float32),
    }
    for b, it in enumerate(items):
        n = it["n"]
        out["types"][b, :n] = it["types"]
        out["attrs"][b, :n] = it["attrs"]
        out["dts"][b, :n] = it["dts"]
        out["next_stage"][b, :n] = it["next_stage"]
        out["tau"][b, :n] = it["tau"]
        out["mask"][b, :n] = True
        out["train_mask"][b, :n] = it.get("train_mask", np.ones(n, bool))
    return out


def collect_texts(sessions: list[dict]) -> list[str]:
    return sorted({e["text"] for s in sessions for e in s["events"] if e["type"] == "MSG_RECV" and e.get("text")})


def payment_rows(session: dict) -> list[dict]:
    """Per-transaction view for the bank-style baseline: only what a payment system sees."""
    rows = []
    v = session.get("victim", {})
    for e in session["events"]:
        if e["type"] == "PAY":
            a = e["attrs"]
            rows.append({
                "amount_ratio": a.get("amount_ratio", 0.0),
                "log_amount": math.log1p(a.get("amount", 0.0)),
                "first_time": int(bool(a.get("first_time"))),
                "hour": int((e["t"] / 3600) % 24),
                "median_txn_log": math.log1p(v.get("median_txn", 1000.0)),
                "label": session["label"],
                "t": e["t"],
            })
    return rows
