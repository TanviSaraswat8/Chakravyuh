"""Train every model and write the benchmark report.

    python -m chakravyuh.ml.train --data data --out artifacts

Splits (by session):
    train         85% of generation-0 sessions + evolved generations 1..k-2
    calib         15% of generation-0 (fusion calibration + conformal thresholds)
    test_seen     separate generation-0 sessions written with HELD-OUT message wordings
    test_evolved  evolved generations k-1..k (mutations the models never saw) + legit from test_seen
    test_holdout  the held-out scam family (e.g. fake e-challan) + legit from test_seen
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import average_precision_score

from ..sim.simulator import rule_detector
from ..sim.taxonomy import STAGE_INDEX
from . import scamseq as ss
from .campaigns import CampaignDetector
from .coevolve import first_payment_index
from .engine import PAYMENT_EVENTS, Engine
from .features import encode_session, payment_rows
from .fusion import Fusion, ece
from .payee_risk import train_payee_model
from .policy import STOP, LinUCBPolicy
from .tagger import TacticTagger


def load_sessions(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def split(sessions: list[dict], seed: int = 0) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    base = [s for s in sessions if s.get("split_hint") == "train_pool"]
    test = [s for s in sessions if s.get("split_hint") == "test_seen"]     # unseen wordings
    held = [s for s in sessions if s.get("split_hint") == "holdout_family"]
    evolved = [s for s in sessions if s.get("split_hint") == "evolved"]
    rng.shuffle(base)
    n = len(base)
    train, calib = base[: int(0.85 * n)], base[int(0.85 * n):]
    gens = sorted({s["generation"] for s in evolved})
    late = set(gens[-2:]) if len(gens) >= 3 else set(gens[-1:])
    train += [s for s in evolved if s["generation"] not in late]
    legit_test = [s for s in test if s["label"] == 0]
    return {
        "train": train, "calib": calib, "test_seen": test,
        "test_evolved": [s for s in evolved if s["generation"] in late] + legit_test,
        "test_holdout": held + legit_test,
    }


# ------------------------------------------------------------------ evaluation
def session_scores(results: list[dict]) -> np.ndarray:
    """Max fused probability *before* money leaves (what matters for prevention)."""
    out = []
    for r in results:
        k = first_payment_index(r["events"])
        ps = [d["p"] for d in r["decisions"][: (k + 1 if k is not None else None)]]
        out.append(max(ps) if ps else 0.0)
    return np.array(out)


def recall_at_far(scores: np.ndarray, y: np.ndarray, far: float) -> tuple[float, float]:
    legit = np.sort(scores[y == 0])
    if not len(legit) or not (y == 1).any():
        return 0.0, 1.0
    thr = legit[min(len(legit) - 1, int(math.ceil(len(legit) * (1 - far))))]
    return float((scores[y == 1] > thr).mean()), float(thr)


PREVALENCE = 0.02   # share of sessions that are scams in the real world (assumption, reported)


def project(alerts_legit_per_1000: float, alerts_per_scam: float) -> float:
    """Alerts per 1,000 users' sessions at realistic scam prevalence."""
    return round((1 - PREVALENCE) * alerts_legit_per_1000 + PREVALENCE * 1000 * alerts_per_scam, 1)


def policy_outcomes(results: list[dict], sessions: list[dict]) -> dict:
    alerts_legit, alerts_scam, legit_interrupted, saved, at_stake, lead = 0, 0, 0, 0.0, 0.0, []
    n_legit = sum(1 for s in sessions if s["label"] == 0)
    n_scam = len(sessions) - n_legit
    for r, s in zip(results, sessions):
        k = first_payment_index(r["events"])
        esc = [i for i, d in enumerate(r["decisions"]) if d["escalated"]]
        if s["label"] == 0:
            alerts_legit += len(esc)
            legit_interrupted += int(any(r["decisions"][i]["level"] >= 2 for i in esc))
            continue
        alerts_scam += len(esc)
        amount = max((e["attrs"].get("amount", 0) for e in s["events"] if e["type"] == "PAY"), default=0)
        at_stake += amount
        before = [i for i in esc if k is None or i <= k]
        if before:
            lvl = max(r["decisions"][i]["level"] for i in before)
            saved += amount * STOP[lvl]
            first = before[0]
            lead.append(STAGE_INDEX["payment"] - STAGE_INDEX.get(r["events"][first]["stage"], 0))
    legit_rate = 1000 * alerts_legit / max(n_legit, 1)
    per_scam = alerts_scam / max(n_scam, 1)
    return {
        "false_alerts_per_1000_legit": round(legit_rate, 1),
        "alerts_per_scam_session": round(per_scam, 2),
        "projected_alerts_per_1000_users": project(legit_rate, per_scam),
        "legit_interrupted_rate": round(legit_interrupted / max(n_legit, 1), 4),
        "expected_loss_prevented_share": round(saved / max(at_stake, 1), 4),
        "alert_utility_rs_per_alert": round(saved / max(alerts_legit + alerts_scam, 1), 0),
        "mean_lead_stages": round(float(np.mean(lead)), 2) if lead else 0.0,
    }


def per_txn_baseline_alerts(model, sessions: list[dict], thr: float) -> dict:
    legit, scam = 0, 0
    n_legit = sum(1 for s in sessions if s["label"] == 0)
    n_scam = len(sessions) - n_legit
    for s in sessions:
        rows = payment_rows(s)
        if rows:
            X = np.array([[r[c] for c in BASE_COLS] for r in rows])
            n = int((model.predict(X) > thr).sum())
            if s["label"]:
                scam += n
            else:
                legit += n
    legit_rate = 1000 * legit / max(n_legit, 1)
    per_scam = scam / max(n_scam, 1)
    return {"false_alerts_per_1000_legit": round(legit_rate, 1), "alerts_per_scam_session": round(per_scam, 2),
            "projected_alerts_per_1000_users": project(legit_rate, per_scam), "mean_lead_stages": 0.0}


BASE_COLS = ["amount_ratio", "log_amount", "first_time", "hour", "median_txn_log"]


def baseline_scores(model, sessions: list[dict]) -> np.ndarray:
    out = []
    for s in sessions:
        rows = payment_rows(s)
        if rows:
            X = np.array([[r[c] for c in BASE_COLS] for r in rows])
            out.append(float(model.predict(X).max()))
        else:
            out.append(0.0)
    return np.array(out)


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="artifacts")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--budget", type=float, default=900.0, help="policy alert budget per 1000 sessions")
    args = ap.parse_args()
    t0 = time.time()
    data, out = Path(args.data), Path(args.out)
    sessions = load_sessions(data / "sessions.jsonl")
    sp = split(sessions)
    print({k: len(v) for k, v in sp.items()})

    print("1/7 tactic tagger")
    tagger = TacticTagger().fit(sp["train"])

    print("2/7 ScamSeq")
    tags = {t: r.to_dict() for t, r in zip(
        sorted({e['text'] for s in sp['train'] for e in s['events'] if e['type'] == 'MSG_RECV' and e.get('text')}),
        tagger.tag_many(sorted({e['text'] for s in sp['train'] for e in s['events']
                                if e['type'] == 'MSG_RECV' and e.get('text')})))}
    enc = [encode_session(s, tags) for s in sp["train"]]
    model = ss.train_scamseq(enc, epochs=args.epochs)

    print("3/7 payee graph model")
    _, payee_scores, payee_metrics = train_payee_model(str(data / "ledger.csv"), str(data / "accounts.csv"))

    engine = Engine(tagger, model, payee_scores)

    print("4/7 fusion + calibration")
    def stack(sess):
        raws = engine.raw_steps(sess)
        keep = np.concatenate([encode_session(s, {})["train_mask"][-len(r["rows"]):] if len(r["rows"]) else
                               np.zeros(0, bool) for s, r in zip(sess, raws)])
        X = np.concatenate([r["rows"] for r in raws])
        y = np.concatenate([[s["label"]] * len(r["rows"]) for s, r in zip(sess, raws)])
        g = np.concatenate([[i] * len(r["rows"]) for i, r in enumerate(raws)])
        return X[keep], y[keep], g[keep]
    X_tr, y_tr, _ = stack(sp["train"])
    X_cal, y_cal, g_cal = stack(sp["calib"])
    engine.fusion = Fusion().fit(X_tr, y_tr, X_cal, y_cal, g_cal)
    print("   session-level conformal thresholds:", {k: round(v, 3) for k, v in engine.fusion.thresholds.items()})
    print("   fusion weights:", engine.fusion.weights())

    print("5/7 alert policy (LinUCB in simulation)")
    raws = engine.raw_steps(sp["train"])
    traces = []
    for s, r in zip(sp["train"], raws):
        p = engine.fusion.predict(r["rows"])
        k = first_payment_index(r["events"])
        amount = max((e["attrs"].get("amount", 0) for e in s["events"] if e["type"] == "PAY"), default=0)
        traces.append({"label": s["label"], "amount_k": amount / 1000.0,
                       "steps": [(float(p[i]), st["stage_pay"], st["tau"], st["amount_ratio"],
                                  k is not None and i > k, r["events"][i]["type"] in PAYMENT_EVENTS)
                                 for i, st in enumerate(r["steps"])]})
    policy = LinUCBPolicy(budget_per_1000=args.budget)
    th = engine.fusion.thresholds
    # Conformal gates: level L may fire only if p exceeds the threshold whose false-alarm rate is eps_L.
    policy.level_gates = [0.0, th["0.005"], th["0.005"], th["0.001"], th["0.001"]]
    policy.min_p_for_hold = th["0.01"]
    policy.fit(traces, epochs=3)
    policy.alpha = 0.0
    engine.policy = policy

    print("6/7 campaign detector")
    res_train = engine.decide(sp["train"])
    emb = np.stack([r["embedding"] for r in res_train])
    camp = CampaignDetector().fit(emb, [s["family"] for s in sp["train"]], [s["label"] for s in sp["train"]],
                                  [[t for e in s["events"] for t in e["tactics"]] for s in sp["train"]])
    engine.campaigns = camp

    print("7/7 benchmark")
    base_model = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, verbose=-1)
    rows = [r for s in sp["train"] for r in payment_rows(s)]
    base_model.fit(np.array([[r[c] for c in BASE_COLS] for r in rows]), np.array([r["label"] for r in rows]))
    base_predict = type("B", (), {"predict": lambda self, X: base_model.predict_proba(X)[:, 1]})()

    report: dict = {"payee_model": payee_metrics, "fusion_weights": engine.fusion.weights(),
                    "conformal_thresholds": engine.fusion.thresholds, "scamseq_params": ss.n_params(model)}
    for name in ["test_seen", "test_evolved", "test_holdout"]:
        sess = sp[name]
        y = np.array([s["label"] for s in sess])
        res = engine.decide(sess)
        ours = session_scores(res)
        res_np = engine.decide(sess, use_payee=False)
        ours_np = session_scores(res_np)
        rules = np.array([rule_detector(s) for s in sess])
        base = baseline_scores(base_predict, sess)
        sec = {}
        for label, sc in [("rules", rules), ("per_txn_lightgbm", base), ("chakravyuh", ours),
                          ("chakravyuh_no_payee_signal", ours_np)]:
            r1, thr = recall_at_far(sc, y, 0.01)
            sec[label] = {"pr_auc": round(float(average_precision_score(y, sc)), 4) if y.any() else None,
                          "recall_at_1pct_far": round(r1, 4)}
            if label == "per_txn_lightgbm":
                sec[label].update(per_txn_baseline_alerts(base_predict, sess, thr))
        sec["chakravyuh"].update(policy_outcomes(res, sess))
        sec["chakravyuh"]["ece"] = round(ece(np.clip(ours, 0, 1), y), 4)
        # emerging-campaign check on this split
        p = ours
        e = np.stack([r["embedding"] for r in res])
        unknown = camp.is_unknown(e, p)
        sec["unknown_flagged_share_of_scams"] = round(float(unknown[y == 1].mean()), 4) if (y == 1).any() else None
        report[name] = sec
        print(f"\n== {name} ({len(sess)} sessions) ==")
        for k, v in sec.items():
            print(f"  {k}: {v}")

    # campaign cards on the holdout split, as an analyst would see them
    res = engine.decide(sp["test_holdout"])
    e = np.stack([r["embedding"] for r in res])
    p = session_scores(res)
    unk = camp.is_unknown(e, p)
    unk_sessions = [s for s, u in zip(sp["test_holdout"], unk) if u]
    cards = camp.cluster(unk_sessions, e[unk]) if len(unk_sessions) else []
    report["campaign_cards_holdout"] = [{k: v for k, v in c.items() if k != "session_ids"} for c in cards]
    print(f"\nCampaign cards on holdout split: {len(cards)}")
    for c in cards[:3]:
        print("  ", c["name"], "| size", c["size"], "|", c["event_sequence"])

    engine.meta = {"trained_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n_train": len(sp["train"]),
                   "report": report}
    engine.save(out)
    (out / "metrics.json").write_text(json.dumps(report, indent=2))
    print(f"\nSaved artifacts to {out}/ in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
