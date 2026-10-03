"""The scoring engine: one object that turns a session prefix into a decision.

events -> tagger (tactics per message) -> ScamSeq (p_scam, next stage, tau)
       -> payee risk lookup -> fusion + calibration -> alert policy -> action + reason

Used identically by training (to build fusion/policy data), evaluation and the API.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..sim.taxonomy import STAGE_INDEX, STAGES
from . import scamseq as ss
from .campaigns import CampaignDetector
from .features import encode_session
from .fusion import Fusion, context_row
from .policy import LEVEL_NAMES, LinUCBPolicy, context
from .tagger import TacticTagger

PAY_STAGES = [STAGE_INDEX["payment_ask"], STAGE_INDEX["payment"], STAGE_INDEX["cashout"]]
PAYEE_PRIOR = 0.05
PAYMENT_EVENTS = {"UPI_OPEN", "PAYEE_NEW", "PAY", "FD_BREAK"}


def flags_upto(events: list[dict]) -> dict:
    f = {"call_unknown": 0, "screen_share": 0, "remote_app": 0, "new_payee": 0, "amount_ratio": 0.0,
         "payee": None}
    for e in events:
        a = e.get("attrs", {})
        if e["type"] == "CALL" and not a.get("known", False):
            f["call_unknown"] = 1
        elif e["type"] == "SCREEN_SHARE":
            f["screen_share"] = 1
        elif e["type"] == "REMOTE_APP":
            f["remote_app"] = 1
        elif e["type"] == "PAYEE_NEW":
            f["new_payee"] = 1
            f["payee"] = a.get("payee", f["payee"])
        elif e["type"] == "PAY":
            f["amount_ratio"] = max(f["amount_ratio"], a.get("amount_ratio", 0.0))
            f["payee"] = a.get("payee", f["payee"])
    return f


@dataclass
class Engine:
    tagger: TacticTagger
    model: ss.ScamSeq
    payee_scores: dict[str, float]
    fusion: Fusion | None = None
    policy: LinUCBPolicy | None = None
    campaigns: CampaignDetector | None = None
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ core
    def tag_events(self, sessions: list[dict], overrides: dict[str, dict] | None = None) -> dict[str, dict]:
        """Tag every message. `overrides` holds tags computed on the phone (privacy mode: no raw text)."""
        overrides = overrides or {}
        texts = sorted({e["text"] for s in sessions for e in s["events"]
                        if e["type"] == "MSG_RECV" and e.get("text") and e["text"] not in overrides})
        tags = {t: r.to_dict() for t, r in zip(texts, self.tagger.tag_many(texts))}
        tags.update(overrides)
        return tags

    def payee_risk(self, vpa: str | None) -> float:
        if not vpa:
            return PAYEE_PRIOR
        return self.payee_scores.get(vpa, PAYEE_PRIOR)

    def raw_steps(self, sessions: list[dict], use_payee: bool = True,
                  tag_overrides: dict[str, dict] | None = None) -> list[dict]:
        """Per-session, per-event model outputs before fusion."""
        tags = self.tag_events(sessions, tag_overrides)
        enc = [encode_session(s, tags) for s in sessions]
        preds = ss.predict(self.model, enc)
        out = []
        for s, pr in zip(sessions, preds):
            events = s["events"][-len(pr["p"]):] if len(pr["p"]) else []
            rows, steps = [], []
            p_msg = 0.0
            for i, e in enumerate(events):
                if e["type"] == "MSG_RECV" and e.get("text") in tags:
                    p_msg = max(p_msg, tags[e["text"]]["p_scam"])
                fl = flags_upto(events[: i + 1])
                r_payee = self.payee_risk(fl["payee"]) if use_payee else PAYEE_PRIOR
                stage_pay = float(pr["next_stage"][i][PAY_STAGES].sum())
                rows.append(context_row(float(pr["p"][i]), p_msg, r_payee, fl, stage_pay))
                steps.append({"p_seq": float(pr["p"][i]), "p_msg": p_msg, "r_payee": r_payee,
                              "stage_pay": stage_pay, "tau": float(pr["tau"][i]),
                              "next_stage": STAGES[int(np.argmax(pr["next_stage"][i][: len(STAGES)]))],
                              "amount_ratio": fl["amount_ratio"], "flags": fl})
            out.append({"rows": np.array(rows, dtype=np.float32), "steps": steps,
                        "embedding": pr["embedding"], "tags": tags, "events": events})
        return out

    def decide(self, sessions: list[dict], use_payee: bool = True,
               tag_overrides: dict[str, dict] | None = None) -> list[dict]:
        """Full pipeline incl. fusion and policy; returns per-event decisions for each session."""
        raws = self.raw_steps(sessions, use_payee, tag_overrides)
        results = []
        for raw in raws:
            p = self.fusion.predict(raw["rows"]) if (self.fusion and len(raw["rows"])) else \
                np.array([st["p_seq"] for st in raw["steps"]])
            level = 0
            decisions = []
            for i, st in enumerate(raw["steps"]):
                s = context(float(p[i]), st["stage_pay"], st["tau"], st["amount_ratio"], level)
                pending = raw["events"][i]["type"] in PAYMENT_EVENTS
                new = self.policy.act(s, level, float(p[i]), payment_pending=pending) if self.policy else level
                escalated = new > level
                level = max(level, new)
                decisions.append({**st, "p": float(p[i]), "level": level, "escalated": escalated,
                                  "action": LEVEL_NAMES[level]})
            results.append({"decisions": decisions, "embedding": raw["embedding"], "tags": raw["tags"],
                            "events": raw["events"]})
        return results

    # -------------------------------------------------------------- persist
    def save(self, d: str | Path) -> None:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "tagger.pkl", "wb") as f:
            pickle.dump(self.tagger, f)
        ss.save(self.model, str(d / "scamseq.pt"))
        (d / "payee_scores.json").write_text(json.dumps(self.payee_scores))
        if self.fusion:
            with open(d / "fusion.pkl", "wb") as f:
                pickle.dump(self.fusion, f)
        if self.policy:
            (d / "policy.json").write_text(json.dumps(self.policy.to_dict()))
        if self.campaigns:
            (d / "campaigns.json").write_text(json.dumps(self.campaigns.to_dict()))
        (d / "meta.json").write_text(json.dumps(self.meta, indent=2))

    @classmethod
    def load(cls, d: str | Path) -> Engine:
        d = Path(d)
        with open(d / "tagger.pkl", "rb") as f:
            tagger = pickle.load(f)
        fusion = None
        if (d / "fusion.pkl").exists():
            with open(d / "fusion.pkl", "rb") as f:
                fusion = pickle.load(f)
        policy = LinUCBPolicy.from_dict(json.loads((d / "policy.json").read_text())) \
            if (d / "policy.json").exists() else None
        camp = CampaignDetector.from_dict(json.loads((d / "campaigns.json").read_text())) \
            if (d / "campaigns.json").exists() else None
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        return cls(tagger, ss.load(str(d / "scamseq.pt")), json.loads((d / "payee_scores.json").read_text()),
                   fusion, policy, camp, meta)
