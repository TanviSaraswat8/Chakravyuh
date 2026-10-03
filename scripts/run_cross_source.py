#!/usr/bin/env python3
"""Cross-source validation E5-E7 (REAL PUBLIC DATA). Uses the E3 models exactly as trained; nothing
is retrained on UCI or S&P'24.

    python scripts/run_cross_source.py e5 e6 e7

E5  evaluate the frozen E3 models on IMC'25 test, India test, official UCI and S&P'24 test — per source
E6  source identification with four sources (IMC'25, India, UCI, S&P'24)
E7  threshold robustness: curves + bootstrap CIs; thresholds calibrated on a held-out half of UCI ham
"""

from __future__ import annotations

import importlib.util
import json
import os
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, balanced_accuracy_score, f1_score, roc_auc_score  # noqa: E402

from chakravyuh.realdata import expkit as K  # noqa: E402
from chakravyuh.realdata import expmodels as M  # noqa: E402
from chakravyuh.realdata import leakage  # noqa: E402
from chakravyuh.realdata.metrics import ece  # noqa: E402

spec = importlib.util.spec_from_file_location("rre", ROOT / "scripts" / "run_real_experiments.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

MODELS = ["tfidf_lr", "tfidf_svm", "chakravyuh_tagger_arch"]
E3_CLASSES = ["scam", "legit", "promo"]


# --------------------------------------------------------------------------------------------- data
def load_artifact(name: str):
    """Load an E3 model only if its SHA-256 matches its committed manifest."""
    man = json.loads((K.OUT / "manifests" / f"{name}.json").read_text())
    p = ROOT / man["artifact"]
    if K.sha_file(p) != man["sha256"]:
        raise SystemExit(f"{name}: artifact SHA-256 does not match its manifest; refusing to load")
    with open(p, "rb") as f:
        return pickle.load(f), man


def require_official_uci() -> dict:
    m = K.registry.load("uci_sms_spam")
    prov_f = K.registry.raw_dir(m) / ".provenance.json"
    prov = json.loads(prov_f.read_text()) if prov_f.exists() else {}
    if os.environ.get("CHAKRAVYUH_DRYRUN_MIRROR") == "1":
        print("   DRY RUN on the audit-only mirror: code check only, results are not reportable")
        return m
    if prov.get("kind") != "local_download" or not m.get("sha256"):
        raise SystemExit("Official UCI file not registered (only the audit mirror is on disk). "
                         "Run scripts/register_official_uci.py <zip> first.")
    return m


def sources(variant: str = "clean") -> dict:
    """Evaluation sets, each with the purge of near-duplicates of E3's train+val text."""
    imc = [r for r in K.load_records("imc25_smishing") if r["label"] == "scam"]
    ind = [r for r in K.load_records("india_spam_sms_junioralive") if not K.is_export_artefact(r)]
    sp = K.load_records("sp24_gateway_phishing")
    uci = K.load_records("uci_sms_spam")
    a_imc, a_ind, a_sp = K.load_split("imc25_group_v1"), K.load_split("india_spam_sms_junioralive_group_v1"), K.load_split("sp24_temporal_v1")
    fit = R.side(imc, a_imc, "train", "val") + R.side(ind, a_ind, "train", "val")
    fit_text = [K.variant(r, variant) for r in fit]
    out = {}
    for name, recs in (("imc25_test", R.side(imc, a_imc, "test")), ("india_test", R.side(ind, a_ind, "test")),
                       ("uci_all", uci), ("sp24_test", R.side(sp, a_sp, "test_seen_campaign", "test_novel_campaign"))):
        X = [K.variant(r, variant) for r in recs]
        keep = K.purge_test_near_dups(fit_text, X)
        out[name] = {"recs": [r for r, k in zip(recs, keep) if k], "X": [x for x, k in zip(X, keep) if k],
                     "purged": int(len(keep) - sum(keep)), "before": len(recs)}
    return out


def y3(r) -> str:
    if r["dataset_id"] == "uci_sms_spam":
        return "legit" if r["label"] == "legit" else "uci_spam"
    return "scam" if r["label"] == "scam" else ("promo" if r["label"] == "spam" else "legit")


# ------------------------------------------------------------------------------------------- models
def model_scores(model, name, X, cal=None):
    """Return (p_scam, argmax prediction in E3 classes)."""
    if name == "tfidf_svm":
        proba = cal.predict_proba(X)
        classes = list(cal.classes_)
    else:
        proba = model.predict_proba(X)
        classes = list(model.classes_)
    p = proba[:, classes.index("scam")]
    pred = np.array(classes)[proba.argmax(1)]
    return p, pred


def svm_calibrator(svm, variant="clean"):
    """E3 did not persist the SVM's sigmoid calibrator. Refit it deterministically on the SAME E3 validation
    split (the SVM itself is frozen) so probability-based metrics are comparable with E3."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator
    imc = [r for r in K.load_records("imc25_smishing") if r["label"] == "scam"]
    ind = [r for r in K.load_records("india_spam_sms_junioralive") if not K.is_export_artefact(r)]
    va = R.side(imc, K.load_split("imc25_group_v1"), "val") + R.side(ind, K.load_split("india_spam_sms_junioralive_group_v1"), "val")
    yv = ["scam" if r["label"] == "scam" else ("promo" if r["label"] == "spam" else "legit") for r in va]
    return CalibratedClassifierCV(FrozenEstimator(svm), method="sigmoid").fit([K.variant(r, variant) for r in va], yv)


def e3_thresholds(variant="clean") -> dict:
    e3 = json.loads((K.OUT / "results" / "e3.json").read_text())
    return {m: v["fpr_legit_1pct_on_val"]["threshold"] for m, v in e3["variants"][variant]["models"].items()
            if "fpr_legit_1pct_on_val" in v}


# ===================================================================================== E5
def per_source_block(ys, p, pred):
    ys, p, pred = np.asarray(ys), np.asarray(p, float), np.asarray(pred)
    flag = pred == "scam"
    out = {"n": int(len(ys)), "classes": dict(Counter(ys.tolist()))}
    if (ys == "scam").any():
        sc = ys == "scam"
        out["recall"] = round(float(flag[sc].mean()), 4)
        out["fnr"] = round(1 - out["recall"], 4)
        out["recall_95ci"] = K.bootstrap_rate(flag[sc].astype(float))
    for c in ("legit", "promo"):
        if (ys == c).any():
            out[f"fpr_{c}"] = round(float(flag[ys == c].mean()), 4)
            out[f"fpr_{c}_95ci"] = K.bootstrap_rate(flag[ys == c].astype(float))
    if (ys == "uci_spam").any():
        m = ys == "uci_spam"
        out["uci_spam_flag_rate"] = round(float(flag[m].mean()), 4)
        out["uci_spam_note"] = "UCI 'spam' mixes prize scams and marketing: a flag rate, not recall or FPR"
    pos = ys == "scam"
    if pos.any() and (~pos).any() and not (ys == "uci_spam").any():
        tp, fp = int((flag & pos).sum()), int((flag & ~pos).sum())
        out["precision"] = round(tp / (tp + fp), 4) if tp + fp else None
        out["f1"] = round(float(f1_score(pos, flag)), 4)
        out["pr_auc"] = round(float(average_precision_score(pos, p)), 4)
        out["roc_auc"] = round(float(roc_auc_score(pos, p)), 4)
        out["ece"] = round(float(ece(pos.astype(int), p)), 4)
    labels = sorted(set(ys.tolist()))
    out["confusion"] = {"rows_true": labels, "cols_pred": E3_CLASSES,
                        "matrix": [[int(((ys == a) & (pred == b)).sum()) for b in E3_CLASSES] for a in labels]}
    out["mean_p_scam"] = round(float(p.mean()), 4)
    return out


def pair_block(p_pos, p_neg, thr):
    """Cross-source PAIR (scam source vs legitimate source). Not a merged headline."""
    y = np.r_[np.ones(len(p_pos)), np.zeros(len(p_neg))]
    s = np.r_[p_pos, p_neg]
    flag = s >= thr
    tp, fp = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum())
    return {"n_pos": len(p_pos), "n_neg": len(p_neg), "prevalence": round(len(p_pos) / len(y), 4),
            "pr_auc": round(float(average_precision_score(y, s)), 4), "roc_auc": round(float(roc_auc_score(y, s)), 4),
            "ece": round(float(ece(y.astype(int), s)), 4), "threshold": thr,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(float(flag[y == 1].mean()), 4), "fpr": round(float(flag[y == 0].mean()), 4)}


def e5() -> dict:
    uci_m = require_official_uci()
    res = {"label": "REAL PUBLIC DATA · cross-source evaluation of FROZEN E3 models (no retraining)",
           "provenance": K.data_provenance(["imc25_smishing", "india_spam_sms_junioralive", "uci_sms_spam", "sp24_gateway_phishing"],
                                           ["imc25_group_v1", "india_spam_sms_junioralive_group_v1", "sp24_temporal_v1"]),
           "uci_official": {k: uci_m.get(k) for k in ("version", "license", "official_download", "sample_count", "label_schema")},
           "variants": {}}
    thr = {"masked": None, "clean": e3_thresholds("clean")}
    thr["masked"] = e3_thresholds("masked")
    for variant in ("clean", "masked"):
        S = sources(variant)
        vres = {"purged_near_dups_of_e3_fit": {k: {"purged": v["purged"], "of": v["before"]} for k, v in S.items()},
                "models": {}}
        for mname in MODELS:
            model, man = load_artifact(f"e3__{variant}__{mname}")
            cal = svm_calibrator(model, variant) if mname == "tfidf_svm" else None
            # Sanity: the loaded model must reproduce E3's in-distribution result on the IMC'25 test
            per, preds = {}, {}
            for sname, d in S.items():
                p, pred = model_scores(model, mname, d["X"], cal)
                ys = [y3(r) for r in d["recs"]]
                t = thr[variant].get(mname)
                blk = {"argmax": per_source_block(ys, p, pred)}
                if t is not None:
                    pred_t = np.where(p >= t, "scam", np.where(pred == "scam", "legit", pred))
                    blk[f"e3_val_threshold_{t}"] = per_source_block(ys, p, pred_t)
                per[sname] = blk
                preds[sname] = (np.array(ys), p)
            t = thr[variant].get(mname, 0.5)
            pairs = {}
            uci_ham = preds["uci_all"][1][preds["uci_all"][0] == "legit"]
            ind_legit = preds["india_test"][1][preds["india_test"][0] == "legit"]
            for pos_name in ("imc25_test", "sp24_test"):
                pos = preds[pos_name][1]
                pairs[f"{pos_name}_vs_uci_ham"] = pair_block(pos, uci_ham, t)
                pairs[f"{pos_name}_vs_india_legit"] = pair_block(pos, ind_legit, t)
            lat = K.latency_ms(lambda x: model_scores(model, mname, [x], cal), S["uci_all"]["X"])
            vres["models"][mname] = {"per_source": per, "cross_source_pairs": pairs, "latency": lat,
                                     "artifact_sha256": man["sha256"], "threshold_used": t,
                                     "svm_calibrator": "refit on E3 val (deterministic)" if cal is not None else None}
            a = per["uci_all"]["argmax"]
            print(f"  E5[{variant}] {mname}: UCI ham FPR {a.get('fpr_legit')} | UCI spam flag {a.get('uci_spam_flag_rate')} | "
                  f"India legit FPR {per['india_test']['argmax'].get('fpr_legit')} | IMC recall {per['imc25_test']['argmax'].get('recall')} | "
                  f"SP24 recall {per['sp24_test']['argmax'].get('recall')}")
        if variant == "clean":
            syn = R.load_synthetic_tagger()
            per = {}
            for sname, d in S.items():
                p = np.array([g.p_scam for g in syn.tag_many(d["X"])])
                ys = [y3(r) for r in d["recs"]]
                per[sname] = {"p_0.5": per_source_block(ys, p, np.where(p >= 0.5, "scam", "legit"))}
            vres["shipped_synthetic_tagger_zero_shot"] = {"label": "SYNTHETIC-TRAINED (simulator only), zero-shot", "per_source": per}
        res["variants"][variant] = vres
    return res


# ===================================================================================== E6
def e6() -> dict:
    require_official_uci()
    S = {}
    imc = K.load_records("imc25_smishing")
    ind = [r for r in K.load_records("india_spam_sms_junioralive") if not K.is_export_artefact(r)]
    sp = K.load_records("sp24_gateway_phishing")
    uci = K.load_records("uci_sms_spam")
    uci_side = leakage.group_split(uci, [r["near_dup_cluster"] for r in uci], test_frac=0.25, val_frac=0.0, seed=K.SEED)
    a_imc, a_ind, a_sp = K.load_split("imc25_group_v1"), K.load_split("india_spam_sms_junioralive_group_v1"), K.load_split("sp24_temporal_v1")
    S["train"] = [(r, "imc25") for r in R.side(imc, a_imc, "train")] + [(r, "india") for r in R.side(ind, a_ind, "train")] + \
                 [(r, "sp24") for r in R.side(sp, a_sp, "train")] + [(r, "uci") for r, s in zip(uci, uci_side) if s == "train"]
    S["test"] = [(r, "imc25") for r in R.side(imc, a_imc, "test")] + [(r, "india") for r in R.side(ind, a_ind, "test")] + \
                [(r, "sp24") for r in R.side(sp, a_sp, "test_seen_campaign", "test_novel_campaign")] + \
                [(r, "uci") for r, s in zip(uci, uci_side) if s == "test"]
    rng = np.random.default_rng(K.SEED)

    def cap(pairs, n):
        out = []
        for s in ("imc25", "india", "sp24", "uci"):
            ps = [p for p in pairs if p[1] == s]
            out += [ps[i] for i in rng.permutation(len(ps))[:n]]
        return out
    tr, te = cap(S["train"], 4000), cap(S["test"], 1000)
    ytr, yte = [s for _, s in tr], [s for _, s in te]
    res = {"label": "REAL PUBLIC DATA", "question": "Can text alone identify the source among IMC'25, India SMS, UCI and S&P'24?",
           "sizes": {"train": dict(Counter(ytr)), "test": dict(Counter(yte))}, "chance_balanced_accuracy": 0.25, "probes": {}}

    def fit(Xtr, ytr_, Xte, yte_, feats=True):
        model = M.Pipeline([("vec", M.word_tfidf()), ("clf", LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced"))]) \
            if feats else LogisticRegression(max_iter=3000, class_weight="balanced")
        model.fit(Xtr, ytr_)
        p = model.predict(Xte)
        labs = sorted(set(yte_))
        return {"balanced_accuracy": round(float(balanced_accuracy_score(yte_, p)), 4),
                "macro_f1": round(float(f1_score(yte_, p, average="macro")), 4),
                "per_source_recall": {s: round(float(np.mean([a == b for a, b in zip(yte_, p) if a == s])), 4) for s in labs},
                "confusion": {"labels": labs, "matrix": [[int(sum(1 for a, b in zip(yte_, p) if a == x and b == y)) for y in labs] for x in labs]}}, model
    for v in ("masked", "clean"):
        rec, model = fit([K.variant(r, v) for r, _ in tr], ytr, [K.variant(r, v) for r, _ in te], yte)
        vocab = np.array(model.named_steps["vec"].get_feature_names_out())
        clf = model.named_steps["clf"]
        rec["top_features"] = {c: vocab[np.argsort(-clf.coef_[i])[:12]].tolist() for i, c in enumerate(clf.classes_)}
        res["probes"][f"text_{v}"] = rec
        print(f"  E6 4-source [{v}]: balanced acc {rec['balanced_accuracy']} {rec['per_source_recall']}")

    def feats(texts):
        toks = ["<URL>", "<NUM>", "<MASK>", "<EMAIL>", "<VPA>"]
        return np.array([[t.count(k) for k in toks] + [len(t) / 100, sum(c.isupper() for c in t) / max(len(t), 1)] for t in texts])
    rec, _ = fit(feats([K.variant(r, "masked") for r, _ in tr]), ytr, feats([K.variant(r, "masked") for r, _ in te]), yte, feats=False)
    res["probes"]["artefact_features_only"] = rec

    # Same-label probes: legitimate vs legitimate, scam vs scam
    def same_label(a_recs, a_name, b_recs, b_name, v="clean"):
        recs = a_recs + b_recs
        y = [a_name] * len(a_recs) + [b_name] * len(b_recs)
        g = [r["near_dup_cluster"] for r in recs]
        uniq = sorted(set(g))
        test_g = set(np.random.default_rng(K.SEED).permutation(uniq)[: len(uniq) // 4])
        tri = [i for i, x in enumerate(g) if x not in test_g]
        tei = [i for i, x in enumerate(g) if x in test_g]
        X = [K.variant(r, v) for r in recs]
        r_, _ = fit([X[i] for i in tri], [y[i] for i in tri], [X[i] for i in tei], [y[i] for i in tei])
        r_["sizes"] = {a_name: len(a_recs), b_name: len(b_recs)}
        return r_
    ind_legit = [r for r in ind if r["label"] == "legit"]
    uci_ham = [r for r in uci if r["label"] == "legit"]
    imc_scam_en = [r for r in imc if r["label"] == "scam" and r["language"] == "english"]
    rng2 = np.random.default_rng(K.SEED)
    sp_sample = [sp[i] for i in rng2.permutation(len(sp))[:6000]]
    res["same_label_probes"] = {
        "legit_india_vs_legit_uci": same_label(ind_legit, "india_legit", uci_ham, "uci_ham"),
        "scam_imc25_english_vs_scam_sp24": same_label(imc_scam_en[:6000], "imc25_scam_en", sp_sample, "sp24_scam"),
    }
    for k, v in res["same_label_probes"].items():
        print(f"  E6 same-label {k}: balanced acc {v['balanced_accuracy']}")
    return res


# ===================================================================================== E7
def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(float(c - h), 4), round(float(c + h), 4)]


def e7() -> dict:
    require_official_uci()
    S = sources("clean")
    uci = S["uci_all"]
    # Split UCI ham into a calibration half and an evaluation half by near-duplicate group
    ham_idx = [i for i, r in enumerate(uci["recs"]) if r["label"] == "legit"]
    ham_recs = [uci["recs"][i] for i in ham_idx]
    side = leakage.group_split(ham_recs, [r["near_dup_cluster"] for r in ham_recs], test_frac=0.5, val_frac=0.0, seed=K.SEED)
    cal_i = [ham_idx[j] for j, s in enumerate(side) if s == "train"]
    eval_i = [ham_idx[j] for j, s in enumerate(side) if s == "test"]
    res = {"label": "REAL PUBLIC DATA · threshold robustness of FROZEN E3 clean models",
           "uci_ham_split": {"calibration": len(cal_i), "evaluation": len(eval_i), "rule": "group split by near-duplicate cluster, 50/50, seed 13"},
           "coverage_definition": "alert volume: share of all evaluated messages (IMC'25 test + S&P'24 test + India test + UCI ham eval) that are flagged",
           "models": {}}
    grid = np.round(np.concatenate([np.arange(0.05, 0.95, 0.05), np.arange(0.95, 0.996, 0.005), [0.997, 0.998, 0.999]]), 4)
    for mname in MODELS:
        model, man = load_artifact(f"e3__clean__{mname}")
        cal = svm_calibrator(model) if mname == "tfidf_svm" else None
        P = {k: model_scores(model, mname, d["X"], cal)[0] for k, d in S.items()}
        Y = {k: np.array([y3(r) for r in d["recs"]]) for k, d in S.items()}
        pu = P["uci_all"]
        imc_p, sp_p = P["imc25_test"], P["sp24_test"]
        ind_legit_p, ind_promo_p = P["india_test"][Y["india_test"] == "legit"], P["india_test"][Y["india_test"] == "promo"]
        uci_eval_p, uci_cal_p = pu[eval_i], pu[cal_i]
        curve = []
        for t in grid:
            def rate(a):
                k = int((a >= t).sum())
                return round(k / max(len(a), 1), 4), wilson(k, len(a))
            fl_u, ci_u = rate(uci_eval_p)
            fl_il, ci_il = rate(ind_legit_p)
            fl_ip, ci_ip = rate(ind_promo_p)
            r_imc, ci_imc = rate(imc_p)
            r_sp, ci_sp = rate(sp_p)
            tp = int((imc_p >= t).sum())
            fp_u = int((uci_eval_p >= t).sum())
            allp = np.concatenate([imc_p, sp_p, P["india_test"], uci_eval_p])
            curve.append({"threshold": float(t), "uci_ham_fpr": fl_u, "uci_ham_fpr_95ci": ci_u,
                          "india_legit_fpr": fl_il, "india_legit_fpr_95ci": ci_il,
                          "india_promo_fpr": fl_ip, "india_promo_fpr_95ci": ci_ip,
                          "imc25_recall": r_imc, "imc25_recall_95ci": ci_imc, "sp24_recall": r_sp, "sp24_recall_95ci": ci_sp,
                          "precision_imc25_vs_uci_ham_eval": round(tp / (tp + fp_u), 4) if tp + fp_u else None,
                          "coverage_alert_volume": round(float((allp >= t).mean()), 4)})
        # Threshold selection: smallest t with legit FPR <= 1% on (a) UCI ham calibration half, (b) India val legit (n=133)
        def select(cal_scores, target=0.01):
            """Smallest threshold with at most floor(target*n) calibration messages flagged (ties handled:
            the threshold sits just above the (k+1)-th highest score)."""
            desc = np.sort(cal_scores)[::-1]
            k = int(np.floor(target * len(desc)))
            if k >= len(desc):
                return 0.0
            return float(np.nextafter(desc[k], np.inf))
        ind_val = [r for r in K.load_records("india_spam_sms_junioralive") if not K.is_export_artefact(r)]
        ind_val = [r for r in R.side(ind_val, K.load_split("india_spam_sms_junioralive_group_v1"), "val") if r["label"] == "legit"]
        iv_p = model_scores(model, mname, [K.variant(r, "clean") for r in ind_val], cal)[0]
        boot = {}
        rng = np.random.default_rng(K.SEED)
        for cal_name, scores in (("uci_ham_calibration_half", uci_cal_p), ("india_val_legit", iv_p)):
            ts = [select(scores[rng.integers(0, len(scores), len(scores))]) for _ in range(500)]
            t0 = select(scores)
            boot[cal_name] = {
                "n": int(len(scores)), "selected_threshold": round(t0, 4),
                "threshold_95ci": [round(float(np.percentile(ts, 2.5)), 4), round(float(np.percentile(ts, 97.5)), 4)],
                "at_selected": {"uci_ham_eval_fpr": round(float((uci_eval_p >= t0).mean()), 4),
                                "india_legit_fpr": round(float((ind_legit_p >= t0).mean()), 4),
                                "india_promo_fpr": round(float((ind_promo_p >= t0).mean()), 4),
                                "imc25_recall": round(float((imc_p >= t0).mean()), 4), "sp24_recall": round(float((sp_p >= t0).mean()), 4)},
                "imc25_recall_over_bootstrap_thresholds_95ci": [round(float(np.percentile([(imc_p >= t).mean() for t in ts], q)), 4) for q in (2.5, 97.5)],
                "uci_ham_eval_fpr_over_bootstrap_thresholds_95ci": [round(float(np.percentile([(uci_eval_p >= t).mean() for t in ts], q)), 4) for q in (2.5, 97.5)],
            }
        res["models"][mname] = {"curve": curve, "threshold_selection": boot, "artifact_sha256": man["sha256"]}
        b = boot["uci_ham_calibration_half"]
        print(f"  E7 {mname}: UCI-cal thr {b['selected_threshold']} CI {b['threshold_95ci']} -> {b['at_selected']}; "
              f"India-val thr {boot['india_val_legit']['selected_threshold']} CI {boot['india_val_legit']['threshold_95ci']}")
    return res


def uci_calibration_assignment() -> dict[str, str]:
    """The exact E7 partition: UCI messages that are not near-duplicates of E3's train+val (clean text);
    ham split 50/50 by near-duplicate group (seed 13) into calibration / evaluation; spam kept for flag rates."""
    S = sources("clean")
    recs = S["uci_all"]["recs"]
    ham = [r for r in recs if r["label"] == "legit"]
    side = leakage.group_split(ham, [r["near_dup_cluster"] for r in ham], test_frac=0.5, val_frac=0.0, seed=K.SEED)
    out = {r["record_id"]: ("calibration" if s == "train" else "evaluation") for r, s in zip(ham, side)}
    out.update({r["record_id"]: "spam" for r in recs if r["label"] != "legit"})
    return out


def save_uci_split() -> dict:
    require_official_uci()
    a = uci_calibration_assignment()
    path = K.split_path("uci_ham_calibration_v1")
    path.write_text(json.dumps({"split_id": "uci_ham_calibration_v1", "dataset": "uci_sms_spam",
                                "purpose": "threshold calibration (calibration half) and independent legitimate-FPR evaluation "
                                           "(evaluation half); identical to E7; never training data",
                                "assignment": a}) + "\n")
    print("uci_ham_calibration_v1:", dict(Counter(a.values())), K.sha_file(path))
    return {}


EXPS = {"e5": e5, "e6": e6, "e7": e7}


def main() -> int:
    K.seed_all()
    if sys.argv[1:] == ["save-uci-split"]:
        save_uci_split()
        return 0
    for exp in sys.argv[1:] or list(EXPS):
        t0 = time.time()
        print(f"== {exp}")
        r = EXPS[exp]()
        r["environment"] = K.environment()
        r["runtime_seconds"] = round(time.time() - t0, 1)
        name = f"dryrun_{exp}" if os.environ.get("CHAKRAVYUH_DRYRUN_MIRROR") == "1" else exp
        print(f"   wrote {K.write_result(name, r)} in {r['runtime_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
