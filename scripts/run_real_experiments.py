#!/usr/bin/env python3
"""Real-data CPU experiments E0-E4 (REAL PUBLIC DATA track). No simulator data, no GPU, no Sentinel.

    python scripts/run_real_experiments.py e0 e1 e2 e3 e4

Prerequisites: make data-real && make splits-real (processed files + leakage-safe splits).
Results: experiments/real/results/<exp>.json. Trained models: experiments/real/artifacts/ (git-ignored)
with a manifest per model in experiments/real/manifests/.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import (average_precision_score, balanced_accuracy_score, f1_score,  # noqa: E402
                             precision_recall_fscore_support, roc_auc_score)

from chakravyuh.realdata import expkit as K  # noqa: E402
from chakravyuh.realdata import expmodels as M  # noqa: E402
from chakravyuh.realdata.metrics import ece  # noqa: E402

TYPES = ["banking", "delivery", "government", "telecom", "wrong number", "hey mum/dad", "others", "spam"]


def per_class(y, p, labels):
    pr, rc, f, s = precision_recall_fscore_support(y, p, labels=labels, zero_division=0)
    return {lab: {"precision": round(float(pr[i]), 4), "recall": round(float(rc[i]), 4), "f1": round(float(f[i]), 4),
                  "support": int(s[i])} for i, lab in enumerate(labels)}


def side(recs, assign, *names):
    return [r for r in recs if assign.get(r["record_id"]) in names]


# ===================================================================================== E0
def e0() -> dict:
    """Can a classifier tell WHICH DATASET a message came from? Artefacts would make E3 untrustworthy."""
    imc, ind, sp = K.load_records("imc25_smishing"), K.load_records("india_spam_sms_junioralive"), K.load_records("sp24_gateway_phishing")
    ind = [r for r in ind if not K.is_export_artefact(r)]
    a_imc, a_ind, a_sp = K.load_split("imc25_group_v1"), K.load_split("india_spam_sms_junioralive_group_v1"), K.load_split("sp24_temporal_v1")
    tr = [(r, "imc25") for r in side(imc, a_imc, "train")] + [(r, "india") for r in side(ind, a_ind, "train")] + \
         [(r, "sp24") for r in side(sp, a_sp, "train")]
    te = [(r, "imc25") for r in side(imc, a_imc, "test")] + [(r, "india") for r in side(ind, a_ind, "test")] + \
         [(r, "sp24") for r in side(sp, a_sp, "test_seen_campaign", "test_novel_campaign")]
    rng = np.random.default_rng(K.SEED)

    def cap(pairs, n):                      # cap each source so the probe is not dominated by volume
        out = []
        for s in ("imc25", "india", "sp24"):
            ps = [p for p in pairs if p[1] == s]
            idx = rng.permutation(len(ps))[:n]
            out += [ps[i] for i in idx]
        return out
    tr, te = cap(tr, 6000), cap(te, 1500)

    def counts_features(texts):
        toks = ["<URL>", "<NUM>", "<MASK>", "<EMAIL>", "<VPA>"]
        return np.array([[t.count(k) for k in toks] + [len(t) / 100, sum(c.isupper() for c in t) / max(len(t), 1)]
                         for t in texts])

    def probe(name, Xtr, ytr, Xte, yte, model):
        model.fit(Xtr, ytr)
        p = model.predict(Xte)
        rec = {"balanced_accuracy": round(float(balanced_accuracy_score(yte, p)), 4),
               "macro_f1": round(float(f1_score(yte, p, average="macro")), 4),
               "per_source_recall": {s: round(float(np.mean([a == b for a, b in zip(yte, p) if a == s])), 4) for s in sorted(set(yte))},
               "chance_balanced_accuracy": round(1 / len(set(yte)), 4)}
        return rec, model

    res = {"label": "REAL PUBLIC DATA", "question": "Does text identify the source dataset (artefact) rather than scam behaviour?",
           "sizes": {"train": dict(Counter(s for _, s in tr)), "test": dict(Counter(s for _, s in te))}, "probes": {}}
    ytr, yte = [s for _, s in tr], [s for _, s in te]
    for v in ("raw", "masked", "stripped", "clean"):
        Xtr, Xte = [K.variant(r, v) for r, _ in tr], [K.variant(r, v) for r, _ in te]
        model = M.Pipeline([("vec", M.word_tfidf()), ("clf", LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced"))])
        rec, model = probe(v, Xtr, ytr, Xte, yte, model)
        vec, clf = model.named_steps["vec"], model.named_steps["clf"]
        vocab = np.array(vec.get_feature_names_out())
        rec["top_features"] = {c: vocab[np.argsort(-clf.coef_[i])[:12]].tolist() for i, c in enumerate(clf.classes_)}
        res["probes"][f"text_{v}"] = rec
    # artefact-only probe: placeholder counts, length and upper-case ratio, nothing about content
    rec, _ = probe("artefacts_only", counts_features([K.variant(r, "masked") for r, _ in tr]), ytr,
                   counts_features([K.variant(r, "masked") for r, _ in te]), yte, LogisticRegression(max_iter=3000, class_weight="balanced"))
    res["probes"]["artefact_features_only"] = rec
    # Controlled probe: SAME label, different source. IMC'25 'spam' class vs India promotional 'spam'.
    imc_spam = [r for r in imc if r["label"] == "spam"]
    ind_spam = [r for r in ind if r["label"] == "spam"]
    ctrl = {}
    imc_spam_en = [r for r in imc_spam if r["language"] == "english"]
    for v in ("masked", "stripped", "clean", "clean_english_only"):
        if v == "clean_english_only":
            imc_spam, v = imc_spam_en, "clean_en"
        X = [K.variant(r, "clean" if v == "clean_en" else v) for r in imc_spam + ind_spam]
        y = ["imc25"] * len(imc_spam) + ["india"] * len(ind_spam)
        groups = [r["near_dup_cluster"] for r in imc_spam + ind_spam]
        uniq = sorted(set(groups))
        test_groups = set(np.random.default_rng(K.SEED).permutation(uniq)[: len(uniq) // 4])
        tri = [i for i, g in enumerate(groups) if g not in test_groups]
        tei = [i for i, g in enumerate(groups) if g in test_groups]
        model = M.Pipeline([("vec", M.word_tfidf()), ("clf", LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced"))])
        r_, _ = probe(v, [X[i] for i in tri], [y[i] for i in tri], [X[i] for i in tei], [y[i] for i in tei], model)
        ctrl[f"text_{v}"] = r_
    res["controlled_same_label_probe"] = {"what": "IMC'25 'spam' (unsolicited) vs India promotional 'spam' — same label, different source; group split by near-duplicate cluster",
                                          "sizes": {"imc25_spam": len(imc_spam), "india_spam": len(ind_spam)}, "results": ctrl}
    # Language cue: share of non-English per source in the probe data
    res["language_cue"] = {"imc25_non_english_share_test": round(float(np.mean([(r.get("language") or "") != "english" for r, s in te if s == "imc25"])), 4),
                           "india_language": "English with some romanised Hindi (no language field)"}
    res["excluded_records"] = {"india_chat_export_artefacts": len(K.load_records("india_spam_sms_junioralive")) - len(ind)}
    res["mitigation"] = ("'stripped' removes placeholder tokens; 'clean' also repairs mojibake (ftfy) and the 35 chat-export "
                         "placeholder rows are excluded. E3 is run on 'masked' and 'clean', and on an English-only IMC'25 subset.")
    return res


# ===================================================================================== E1
def e1() -> dict:
    recs = [r for r in K.load_records("imc25_smishing") if r["label"] != "unknown" and r["scam_type"] in TYPES]
    a = K.load_split("imc25_group_v1")
    tr, va, te = side(recs, a, "train"), side(recs, a, "val"), side(recs, a, "test")
    X = {k: [r["text_masked"] for r in v] for k, v in (("tr", tr), ("va", va), ("te", te))}
    y = {k: [r["scam_type"] for r in v] for k, v in (("tr", tr), ("va", va), ("te", te))}
    res = {"label": "REAL PUBLIC DATA · WEAKLY LABELLED (GPT-4o scam_type; kappa 0.93 vs humans on 150 English msgs)",
           "task": "8-class scam type", "split": "imc25_group_v1", "text_variant": "masked",
           "class_distribution": {k: dict(Counter(v)) for k, v in y.items()}, "models": {},
           "provenance": K.data_provenance(["imc25_smishing"], ["imc25_group_v1"])}
    idx = {c: i for i, c in enumerate(TYPES)}

    def evaluate(name, pred, proba=None, classes=None, model=None, predict_one=None, extra=None):
        out = {"macro_f1": round(float(f1_score(y["te"], pred, average="macro", labels=TYPES, zero_division=0)), 4),
               "accuracy": round(float(np.mean(np.array(pred) == np.array(y["te"]))), 4),
               "per_class": per_class(y["te"], pred, TYPES), "confusion": K.confusion(y["te"], list(pred), TYPES)}
        if proba is not None:
            order = [list(classes).index(c) for c in TYPES]
            P = proba[:, order]
            out["ece_top_label"] = round(K.ece_top_label(P, np.array([idx[c] for c in y["te"]])), 4)
        if predict_one:
            out["latency"] = K.latency_ms(predict_one, X["te"])
        en = [i for i, r in enumerate(te) if r["language"] == "english"]
        out["macro_f1_english_only"] = round(float(f1_score([y["te"][i] for i in en], [pred[i] for i in en], average="macro", labels=TYPES, zero_division=0)), 4)
        out["macro_f1_non_english"] = round(float(f1_score([y["te"][i] for i in range(len(te)) if i not in set(en)],
                                                           [pred[i] for i in range(len(te)) if i not in set(en)], average="macro", labels=TYPES, zero_division=0)), 4)
        if extra:
            out.update(extra)
        if model is not None:
            out.update(K.save_artifact(model, "e1", name, {"task": "scam_type", "split": "imc25_group_v1", "config": extra or {},
                                                            "provenance": res["provenance"]}))
        res["models"][name] = out
        print(f"  E1 {name}: macro-F1 {out['macro_f1']}")

    rules = M.RulesClassifier(M.SCAM_TYPE_LEXICON, "others")
    t0 = time.time()
    evaluate("rules", rules.predict(X["te"]), predict_one=lambda t: rules.predict([t]),
             extra={"lexicon": "expmodels.SCAM_TYPE_LEXICON (English + es/nl/fr/de terms)", "train_seconds": 0})
    t0 = time.time()
    lr, tried = M.tfidf_lr(X["tr"], y["tr"], X["va"], y["va"])
    evaluate("tfidf_lr", lr.predict(X["te"]), lr.predict_proba(X["te"]), lr.classes_, lr, lambda t: lr.predict([t]),
             {"features": "word 1-2-gram TF-IDF, min_df 2, sublinear, max 200k", "clf": "LogisticRegression balanced",
              "C_val_macro_f1": tried, "train_seconds": round(time.time() - t0, 1)})
    t0 = time.time()
    svm, tried, cal = M.tfidf_svm(X["tr"], y["tr"], X["va"], y["va"])
    evaluate("tfidf_svm", svm.predict(X["te"]), cal.predict_proba(X["te"]), cal.classes_, svm, lambda t: svm.predict([t]),
             {"features": "word 1-2-gram TF-IDF", "clf": "LinearSVC balanced; probabilities via sigmoid calibration on val (ECE only)",
              "C_val_macro_f1": tried, "train_seconds": round(time.time() - t0, 1)})
    t0 = time.time()
    tg = M.tagger_arch(X["tr"], y["tr"])
    evaluate("chakravyuh_tagger_arch", tg.predict(X["te"]), tg.predict_proba(X["te"]), tg.classes_, tg, lambda t: tg.predict([t]),
             {"features": "char_wb 2-5 TF-IDF, 60k (identical to TacticTagger)", "clf": "OvR LogisticRegression C=4 balanced",
              "train_seconds": round(time.time() - t0, 1)})
    t0 = time.time()
    tf = M.CharTransformer(TYPES, epochs=5).fit(X["tr"], y["tr"], X["va"], y["va"], M.macro_f1)
    evaluate("char_transformer_scratch", tf.predict(X["te"]), tf.predict_proba(X["te"]), TYPES, tf, lambda t: tf.predict([t]),
             {"config": tf.config(), "history": tf.history, "train_seconds": round(time.time() - t0, 1),
              "note": "trained from scratch on CPU; no pretrained weights"})
    res["existing_synthetic_tagger"] = "N/A for E1: the shipped tagger has no scam-type head (it predicts tactics, stage, p_scam)."
    return res


# ===================================================================================== E2
LURE_TO_TACTIC = {"authority": "authority", "time/urgency": "urgency", "need and greed": "greed",
                  "herd": "social_proof", "kindness": "reciprocity"}


def load_synthetic_tagger():
    """The shipped tagger, trained ONLY on simulator data. Loaded through Engine.load so its SHA-256
    manifest is verified first."""
    from chakravyuh.ml.engine import Engine
    return Engine.load(K.registry.REPO / "backend" / "artifacts").tagger


def multilabel_report(Y, P, labels):
    Y, P = np.asarray(Y), np.asarray(P)
    out = {"micro_f1": round(float(f1_score(Y, P, average="micro", zero_division=0)), 4),
           "macro_f1": round(float(f1_score(Y, P, average="macro", zero_division=0)), 4), "per_label": {}}
    for j, lab in enumerate(labels):
        tp = int(((P[:, j] == 1) & (Y[:, j] == 1)).sum())
        fp = int(((P[:, j] == 1) & (Y[:, j] == 0)).sum())
        fn = int(((P[:, j] == 0) & (Y[:, j] == 1)).sum())
        tn = int(((P[:, j] == 0) & (Y[:, j] == 0)).sum())
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        out["per_label"][lab] = {"precision": round(pr, 4), "recall": round(rc, 4),
                                 "f1": round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0, "support": int(Y[:, j].sum()),
                                 "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}}
    return out


def e2() -> dict:
    labels = M.LURE_LABELS
    recs = [r for r in K.load_records("imc25_smishing") if r["label"] == "scam" and r["lures"]]
    a = K.load_split("imc25_group_v1")
    tr, va, te = side(recs, a, "train"), side(recs, a, "val"), side(recs, a, "test")
    X = {k: [r["text_masked"] for r in v] for k, v in (("tr", tr), ("va", va), ("te", te))}
    Y = {k: np.array([[int(lab in r["lures"]) for lab in labels] for r in v]) for k, v in (("tr", tr), ("va", va), ("te", te))}
    res = {"label": "REAL PUBLIC DATA · WEAKLY LABELLED: lures were assigned by GPT-4o (Stajano & Wilson typology); "
                    "GPT-4o vs humans kappa 0.70 on 150 English messages. Scores measure agreement with GPT-4o, NOT accuracy against human ground truth.",
           "task": "7-label multi-label lure tagging (scam messages with at least one lure)", "split": "imc25_group_v1",
           "label_prevalence_test": {lab: int(Y["te"][:, j].sum()) for j, lab in enumerate(labels)},
           "label_prevalence_train": {lab: int(Y["tr"][:, j].sum()) for j, lab in enumerate(labels)},
           "sizes": {k: len(v) for k, v in (("train", tr), ("val", va), ("test", te))}, "models": {},
           "provenance": K.data_provenance(["imc25_smishing"], ["imc25_group_v1"])}

    def add(name, P, model=None, predict_one=None, extra=None):
        out = multilabel_report(Y["te"], P, labels)
        if predict_one:
            out["latency"] = K.latency_ms(predict_one, X["te"])
        out.update(extra or {})
        if model is not None:
            out.update(K.save_artifact(model, "e2", name, {"task": "lures", "split": "imc25_group_v1", "config": extra or {},
                                                            "provenance": res["provenance"]}))
        res["models"][name] = out
        print(f"  E2 {name}: micro {out['micro_f1']} macro {out['macro_f1']}")

    rules = M.RulesMultiLabel(M.LURE_LEXICON, labels)
    add("rules", rules.predict(X["te"]), predict_one=lambda t: rules.predict([t]), extra={"lexicon": "expmodels.LURE_LEXICON"})
    t0 = time.time()
    lr, tried = M.tfidf_lr(X["tr"], Y["tr"], X["va"], Y["va"], multilabel=True)
    add("tfidf_lr", lr.predict(X["te"]), lr, lambda t: lr.predict([t]),
        {"clf": "OvR LogisticRegression balanced, threshold 0.5", "C_val_macro_f1": tried, "train_seconds": round(time.time() - t0, 1)})
    t0 = time.time()
    svm, tried, _ = M.tfidf_svm(X["tr"], Y["tr"], X["va"], Y["va"], multilabel=True)
    add("tfidf_svm", svm.predict(X["te"]), svm, lambda t: svm.predict([t]),
        {"clf": "OvR LinearSVC balanced, decision 0", "C_val_macro_f1": tried, "train_seconds": round(time.time() - t0, 1)})
    t0 = time.time()
    tg = M.tagger_arch(X["tr"], Y["tr"], multilabel=True)
    add("chakravyuh_tagger_arch", tg.predict(X["te"]), tg, lambda t: tg.predict([t]),
        {"clf": "char_wb 2-5 TF-IDF + OvR LR C=4 balanced (TacticTagger pipeline)", "train_seconds": round(time.time() - t0, 1)})
    res["char_transformer_scratch"] = "CPU-trained from-scratch char transformer skipped: in E1 it took 1,141 s (5 epochs x ~220 s on 2 CPUs) and reached macro-F1 0.473 vs 0.776 for TF-IDF+LR (no pretrained weights available here). Deferred to GPU with a pretrained model."
    # Shipped synthetic-trained tagger, zero-shot, only on the 5 lures with a tactic equivalent.
    syn = load_synthetic_tagger()
    mapped = [lab for lab in labels if lab in LURE_TO_TACTIC]
    tags = syn.tag_many([K.stripped(t) for t in X["te"]])
    P = np.array([[int(LURE_TO_TACTIC[lab] in g.tactics) for lab in mapped] for g in tags])
    Yi = Y["te"][:, [labels.index(lab) for lab in mapped]]
    out = multilabel_report(Yi, P, mapped)
    out["label"] = "SYNTHETIC-TRAINED model (simulator only), evaluated zero-shot on REAL PUBLIC DATA; 5 mapped lures only"
    out["latency"] = K.latency_ms(lambda t: syn.tag_many([t]), [K.stripped(t) for t in X["te"]])
    res["models"]["shipped_synthetic_tagger_zero_shot"] = out
    print(f"  E2 shipped synthetic tagger: micro {out['micro_f1']}")
    return res


# ===================================================================================== E3
E3_CLASSES = ["scam", "legit", "promo"]


def binary_block(y3, p_scam, pred3, n_boot=True):
    """scam = positive. FPR reported separately for legitimate and promotional messages."""
    y3, pred3, p_scam = np.asarray(y3), np.asarray(pred3), np.asarray(p_scam, dtype=float)
    yb, pb = (y3 == "scam").astype(int), (pred3 == "scam").astype(int)
    tp, fn = int(((pb == 1) & (yb == 1)).sum()), int(((pb == 0) & (yb == 1)).sum())
    fp = int(((pb == 1) & (yb == 0)).sum())
    out = {"n": int(len(yb)), "scam": int(yb.sum()), "legit": int((y3 == "legit").sum()), "promo": int((y3 == "promo").sum()),
           "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None,
           "fnr": round(fn / (tp + fn), 4) if tp + fn else None}
    if out["precision"] is not None and out["recall"] is not None and out["precision"] + out["recall"]:
        out["f1"] = round(2 * out["precision"] * out["recall"] / (out["precision"] + out["recall"]), 4)
    for c in ("legit", "promo"):
        m = y3 == c
        if m.any():
            flags = pb[m].astype(float)
            out[f"fpr_{c}"] = round(float(flags.mean()), 4)
            out[f"fpr_{c}_95ci"] = K.bootstrap_rate(flags) if n_boot else None
    if yb.any() and (~yb.astype(bool)).any():
        out["pr_auc"] = round(float(average_precision_score(yb, p_scam)), 4)
        out["roc_auc"] = round(float(roc_auc_score(yb, p_scam)), 4)
        out["ece_scam_probability"] = round(float(ece(yb, p_scam)), 4)
    else:
        out["note"] = "single-class subset: recall/FNR only"
    out["recall_95ci"] = K.bootstrap_rate(pb[yb == 1].astype(float)) if yb.any() else None
    return out


def e3() -> dict:
    imc = [r for r in K.load_records("imc25_smishing") if r["label"] == "scam"]
    ind = [r for r in K.load_records("india_spam_sms_junioralive") if not K.is_export_artefact(r)]
    sp = K.load_records("sp24_gateway_phishing")
    a_imc, a_ind, a_sp = K.load_split("imc25_group_v1"), K.load_split("india_spam_sms_junioralive_group_v1"), K.load_split("sp24_temporal_v1")

    def lab(r):
        return "scam" if r["label"] == "scam" else ("promo" if r["label"] == "spam" else "legit")
    parts = {k: side(imc, a_imc, k) + side(ind, a_ind, k) for k in ("train", "val", "test")}
    res = {"label": "REAL PUBLIC DATA (IMC'25 scams + India SMS legitimate/promotional). The legitimate and promotional "
                    "classes are small and come from a different source than the scams (see E0): treat in-distribution "
                    "numbers as optimistic.",
           "task": "3-class scam / legit / promo; scam is the positive class for binary metrics",
           "splits": ["imc25_group_v1", "india_spam_sms_junioralive_group_v1", "sp24_temporal_v1 (external test only)"],
           "class_distribution": {k: dict(Counter(lab(r) for r in v)) for k, v in parts.items()},
           "provenance": K.data_provenance(["imc25_smishing", "india_spam_sms_junioralive", "sp24_gateway_phishing"],
                                           ["imc25_group_v1", "india_spam_sms_junioralive_group_v1", "sp24_temporal_v1"]),
           "variants": {}}
    moz_raw = K.registry.raw_dir(K.registry.load("moz_smishing"))
    res["moz_smishing"] = ("UNSUPPORTED: not acquired (requires local download) and dataset licence unresolved; not evaluated."
                           if not moz_raw.exists() else "present")
    for v in ("masked", "clean"):
        X = {k: [K.variant(r, v) for r in parts[k]] for k in parts}
        Y = {k: [lab(r) for r in parts[k]] for k in parts}
        keep = K.purge_test_near_dups(X["train"] + X["val"], X["test"])
        te_recs = [r for r, k in zip(parts["test"], keep) if k]
        Xte, Yte = [x for x, k in zip(X["test"], keep) if k], [y for y, k in zip(Y["test"], keep) if k]
        sp_te = side(sp, a_sp, "test_seen_campaign", "test_novel_campaign")
        sp_X = [K.variant(r, v) for r in sp_te]
        sp_keep = K.purge_test_near_dups(X["train"] + X["val"], sp_X)
        sp_te = [r for r, k in zip(sp_te, sp_keep) if k]
        sp_X = [x for x, k in zip(sp_X, sp_keep) if k]
        vres = {"purged_test_near_duplicates_of_train": int(len(keep) - sum(keep)),
                "purged_sp24_near_duplicates_of_train": int(len(sp_keep) - sum(sp_keep)),
                "test_distribution_after_purge": dict(Counter(Yte)), "models": {}}

        def run(name, proba_fn, classes, model=None, predict_one=None, extra=None, val_proba=None):
            P = proba_fn(Xte)
            ci = list(classes).index("scam")
            p_scam = P[:, ci]
            pred = np.array(classes)[P.argmax(1)]
            out = {"argmax_decision": binary_block(Yte, p_scam, pred),
                   "confusion_3class": K.confusion(Yte, list(pred), E3_CLASSES)}
            # Operating point: highest-recall threshold with legit FPR <= 1% on VALIDATION (n is small: see note)
            if val_proba is not None:
                pv = val_proba[:, ci]
                legit_v = np.array([y == "legit" for y in Y["val"]])
                cands = np.unique(np.concatenate([pv, [1.0]]))
                thr = next(t for t in sorted(cands) if (pv[legit_v] >= t).mean() <= 0.01)
                pred_t = np.where(p_scam >= thr, "scam", np.where(pred == "scam", "legit", pred))
                out["fpr_legit_1pct_on_val"] = {"threshold": round(float(thr), 4), "val_legit_n": int(legit_v.sum()),
                                                **binary_block(Yte, p_scam, pred_t)}
            subsets = {
                "imc25_english_only": [i for i, r in enumerate(te_recs) if r["dataset_id"] == "imc25_smishing" and r["language"] == "english"],
                "imc25_non_english": [i for i, r in enumerate(te_recs) if r["dataset_id"] == "imc25_smishing" and r["language"] != "english"],
                "imc25_india_network": [i for i, r in enumerate(te_recs) if r["dataset_id"] == "imc25_smishing" and r["country"] == "IND"],
            }
            out["subsets_recall"] = {k: {"n": len(ix), "recall": round(float(np.mean(pred[ix] == "scam")), 4) if ix else None}
                                     for k, ix in subsets.items()}
            Ps = proba_fn(sp_X)
            ps_pred = np.array(classes)[Ps.argmax(1)]
            out["external_sp24"] = {"label": "EXTERNAL TEST (unseen source, scams only: recall/FNR only)",
                                    **{k: {"n": int(sum(1 for r in sp_te if a_sp[r['record_id']] == k)),
                                           "recall_argmax": round(float(np.mean([p == "scam" for p, r in zip(ps_pred, sp_te) if a_sp[r['record_id']] == k])), 4)}
                                       for k in ("test_seen_campaign", "test_novel_campaign")}}
            if "fpr_legit_1pct_on_val" in out:
                thr = out["fpr_legit_1pct_on_val"]["threshold"]
                out["external_sp24"]["recall_at_val_threshold"] = round(float(np.mean(Ps[:, ci] >= thr)), 4)
            if predict_one:
                out["latency"] = K.latency_ms(predict_one, Xte)
            out.update(extra or {})
            if model is not None:
                out.update(K.save_artifact(model, "e3", f"{v}__{name}", {"task": "scam/legit/promo", "text_variant": v,
                                                                          "config": extra or {}, "provenance": res["provenance"]}))
            vres["models"][name] = out
            a = out["argmax_decision"]
            print(f"  E3[{v}] {name}: P {a['precision']} R {a['recall']} FPR-legit {a.get('fpr_legit')} FPR-promo {a.get('fpr_promo')} SP24-novel {out['external_sp24']['test_novel_campaign']['recall_argmax']}")

        rules = M.RulesClassifier(M.SCAM_LEGIT_PROMO_LEXICON, "legit")
        run("rules", lambda T: rules.predict_proba(T), rules.classes_, predict_one=lambda t: rules.predict([t]),
            extra={"lexicon": "expmodels.SCAM_LEGIT_PROMO_LEXICON"})
        t0 = time.time()
        lr, tried = M.tfidf_lr(X["train"], Y["train"], X["val"], Y["val"])
        run("tfidf_lr", lr.predict_proba, lr.classes_, lr, lambda t: lr.predict([t]),
            {"clf": "LogisticRegression balanced", "C_val_macro_f1": tried, "train_seconds": round(time.time() - t0, 1)},
            val_proba=lr.predict_proba(X["val"]))
        t0 = time.time()
        svm, tried, cal = M.tfidf_svm(X["train"], Y["train"], X["val"], Y["val"])
        run("tfidf_svm", cal.predict_proba, cal.classes_, svm, lambda t: svm.predict([t]),
            {"clf": "LinearSVC balanced; probabilities = sigmoid calibration fitted on val (so the val-threshold rule is optimistic)",
             "C_val_macro_f1": tried, "train_seconds": round(time.time() - t0, 1)}, val_proba=cal.predict_proba(X["val"]))
        t0 = time.time()
        tg = M.tagger_arch(X["train"], Y["train"])
        run("chakravyuh_tagger_arch", tg.predict_proba, tg.classes_, tg, lambda t: tg.predict([t]),
            {"clf": "TacticTagger pipeline retrained", "train_seconds": round(time.time() - t0, 1)}, val_proba=tg.predict_proba(X["val"]))
        if v == "clean":
            vres["char_transformer_scratch"] = "CPU-trained from-scratch char transformer skipped: in E1 it took 1,141 s (5 epochs x ~220 s on 2 CPUs) and reached macro-F1 0.473 vs 0.776 for TF-IDF+LR (no pretrained weights available here). Deferred to GPU with a pretrained model."
            syn = load_synthetic_tagger()

            def syn_proba(T):
                p = np.array([g.p_scam for g in syn.tag_many(T)])
                return np.stack([p, 1 - p, np.zeros_like(p)], 1)       # binary model: no promo class
            run("shipped_synthetic_tagger_zero_shot", syn_proba, E3_CLASSES, predict_one=lambda t: syn.tag_many([t]),
                extra={"label": "SYNTHETIC-TRAINED (simulator only) p_scam, zero-shot on REAL PUBLIC DATA; binary, no promo class"},
                val_proba=syn_proba(X["val"]))
        res["variants"][v] = vres
    return res


# ===================================================================================== E4
def e4() -> dict:
    from datetime import datetime

    from sklearn.cluster import HDBSCAN
    from sklearn.decomposition import TruncatedSVD
    from sklearn.metrics import adjusted_rand_score, completeness_score, homogeneity_score, normalized_mutual_info_score

    from chakravyuh.ml.campaigns import CampaignDetector
    from chakravyuh.realdata.adapters import sp24_campaigns
    from chakravyuh.realdata.textnorm import template_key

    recs = K.load_records("sp24_gateway_phishing")
    a = K.load_split("sp24_temporal_v1")
    meta = K.load_split.__globals__["json"].loads(K.split_path("sp24_temporal_v1").read_text())
    vcut, cut = meta["val_cut"], meta["test_cut"]
    ts = lambda r: datetime.fromisoformat(r["timestamp"]).timestamp()  # noqa: E731
    tr, va = side(recs, a, "train"), side(recs, a, "val")
    te = sorted(side(recs, a, "test_seen_campaign", "test_novel_campaign"), key=lambda r: r["timestamp"])
    camps = list(sp24_campaigns(K.registry.raw_dir(K.registry.load("sp24_gateway_phishing"))))
    by_key = {}
    for c in camps:
        by_key.setdefault(template_key(c["template"]), []).append(c)

    def authors_campaign(r):
        cs = by_key.get(template_key(r["text"]))
        if not cs:
            return None
        t = ts(r)
        inside = [c for c in cs if c["first_seen"] - 1 <= t <= c["last_seen"] + 1]
        return (inside or sorted(cs, key=lambda c: abs(c["first_seen"] - t)))[0]
    vcut_t = datetime.fromisoformat(vcut).timestamp()
    train_keys = {template_key(r["text"]) for r in tr}
    gtA = np.array([a[r["record_id"]] == "test_novel_campaign" for r in te])
    gtB = np.array([template_key(r["text"]) not in train_keys for r in te])
    ac = [authors_campaign(r) for r in te]
    mappedC = np.array([c is not None for c in ac])
    gtC = np.array([c is not None and c["first_seen"] >= vcut_t for c in ac])

    # Embeddings: char TF-IDF fitted on TRAIN text only (no test information)
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=100_000, sublinear_tf=True)
    tr_text = sorted({r["text_masked"] for r in tr})
    Xtr = vec.fit_transform(tr_text)
    Xte = vec.transform([r["text_masked"] for r in te])
    Xva = vec.transform([r["text_masked"] for r in va])

    def max_cos(X):
        out = np.zeros(X.shape[0])
        for b in range(0, X.shape[0], 2000):
            out[b: b + 2000] = (X[b: b + 2000] @ Xtr.T).max(axis=1).toarray().ravel()
        return out
    nov_te, nov_va = 1 - max_cos(Xte), 1 - max_cos(Xva)
    va_known = np.array([template_key(r["text"]) in train_keys for r in va])
    tau = float(np.quantile(nov_va[va_known], 0.95))       # 5% false flags on known-template val messages

    svd = TruncatedSVD(128, random_state=K.SEED).fit(Xtr)
    Etr, Ete = svd.transform(Xtr), svd.transform(Xte)
    t0 = time.time()
    hdb = HDBSCAN(min_cluster_size=5, copy=True).fit(Etr)
    fam = hdb.labels_
    det = CampaignDetector().fit(Etr, [str(f) for f in fam], [int(f >= 0) for f in fam], [[] for _ in fam])
    d_te = det.distance(Ete)
    unknown = det.is_unknown(Ete, np.ones(len(te)))
    det_seconds = round(time.time() - t0, 1)

    def score_block(gt, score, flag, mask=None):
        mask = np.ones(len(gt), bool) if mask is None else mask
        g, sc, fl = gt[mask], score[mask], flag[mask]
        tp, fp = int((fl & g).sum()), int((fl & ~g).sum())
        fn, tn = int((~fl & g).sum()), int((~fl & ~g).sum())
        ci = None
        if 0 < g.sum() < len(g):
            rng, boots = np.random.default_rng(K.SEED), []
            pos, neg = np.where(g)[0], np.where(~g)[0]
            for _ in range(500):            # stratified bootstrap of AUROC
                ix = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
                boots.append(roc_auc_score(g[ix], sc[ix]))
            ci = [round(float(np.percentile(boots, 2.5)), 4), round(float(np.percentile(boots, 97.5)), 4)]
        return {"n": int(mask.sum()), "novel": int(g.sum()), "known": int((~g).sum()),
                "auroc": round(float(roc_auc_score(g, sc)), 4) if 0 < g.sum() < len(g) else None, "auroc_95ci": ci,
                "auprc_novel": round(float(average_precision_score(g, sc)), 4) if g.any() else None,
                "flag_precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "flag_recall": round(tp / (tp + fn), 4) if tp + fn else None,
                "flag_fpr_on_known": round(fp / (fp + tn), 4) if fp + tn else None}
    res = {"label": "REAL PUBLIC DATA · EXTERNAL-STYLE TEMPORAL TEST (gateway messages, not victim sessions)",
           "split": {"id": "sp24_temporal_v1", "val_cut": vcut, "test_cut": cut,
                     "sizes": {"train": len(tr), "val": len(va), "test": len(te)}},
           "provenance": K.data_provenance(["sp24_gateway_phishing"], ["sp24_temporal_v1"]),
           "ground_truths": {
               "A_near_dup_cluster_novel": "test message's near-duplicate cluster (MinHash Jaccard>=0.8) never appears in train — the split's own definition; partly circular with text-similarity detectors",
               "B_exact_template_novel": "normalised template never appears in train",
               "C_authors_campaign_novel": "authors' campaign (matched by template + time) started after the training cut; independent of our clustering",
               "C_mapped_share": round(float(mappedC.mean()), 4)},
           "detectors": {
               "D1_knn_novelty": {"what": "1 - max cosine(char 3-5 TF-IDF) to any train message; flag if > tau",
                                  "tau": round(tau, 4), "tau_rule": "95th percentile on val messages with a train template"},
               "D2_campaign_detector": {"what": "current CampaignDetector algorithm: HDBSCAN(min_cluster_size=5) on SVD-128 of train messages -> cluster prototypes; unknown if distance > delta (97% quantile of train distances)",
                                        "train_clusters": int(len(set(fam)) - (1 if -1 in fam else 0)), "train_noise_share": round(float((fam == -1).mean()), 4),
                                        "delta": round(det.delta, 4), "fit_seconds": det_seconds}},
           "results": {}}
    for gname, gt, mask in (("A", gtA, None), ("B", gtB, None), ("C", gtC, mappedC)):
        res["results"][f"GT_{gname}"] = {"D1_knn": score_block(gt, nov_te, nov_te > tau, mask),
                                         "D2_campaign_detector": score_block(gt, d_te, unknown, mask)}
    # Temporal behaviour: per test day
    days = {}
    for i, r in enumerate(te):
        days.setdefault(r["timestamp"][:10], []).append(i)
    res["temporal_by_day"] = {d: {"n": len(ix), "novel_share_C": round(float(gtC[ix][mappedC[ix]].mean()), 4) if mappedC[ix].any() else None,
                                  "D1_auroc_A": round(float(roc_auc_score(gtA[ix], nov_te[ix])), 4) if 10 <= gtA[ix].sum() <= len(ix) - 10 else None,
                                  "D1_flag_rate": round(float((nov_te[ix] > tau).mean()), 4)}
                              for d, ix in sorted(days.items())}
    # Cluster agreement with the authors' campaign IDs (test period, mapped messages)
    uniq = sorted({r["text_masked"] for r in te})
    pos = {t: i for i, t in enumerate(uniq)}
    hdb_te = HDBSCAN(min_cluster_size=3, copy=True).fit(svd.transform(vec.transform(uniq))).labels_
    ours = np.array([hdb_te[pos[r["text_masked"]]] if hdb_te[pos[r["text_masked"]]] >= 0 else -(pos[r["text_masked"]] + 2) for r in te])
    mi = np.where(mappedC)[0]
    authors = np.array([ac[i]["campaign_id"] for i in mi])
    neardup = np.array([te[i]["near_dup_cluster"] for i in mi])

    def agree(pred, gold):
        return {"ari": round(float(adjusted_rand_score(gold, pred)), 4), "nmi": round(float(normalized_mutual_info_score(gold, pred)), 4),
                "homogeneity": round(float(homogeneity_score(gold, pred)), 4), "completeness": round(float(completeness_score(gold, pred)), 4),
                "n_pred_clusters": int(len(set(pred))), "n_gold": int(len(set(gold)))}
    res["cluster_agreement_vs_authors_campaigns"] = {
        "hdbscan_on_test_messages": agree(ours[mi], authors), "our_near_dup_clusters": agree(neardup, authors),
        "note": "Authors split campaigns by URL and time (median duration < 1 day), so text-only clusters are expected to be "
                "homogeneous but incomplete with respect to their IDs."}
    # Early signal: streaming over the test window
    order = np.arange(len(te))
    flagged = nov_te > tau
    groups, member_group = [], np.full(len(te), -1)
    Xn = Xte
    for i in order:
        if not flagged[i]:
            continue
        best, best_s = -1, 0.5
        for gi, g in enumerate(groups[-500:], start=max(0, len(groups) - 500)):
            sim = float((Xn[i] @ Xn[g["leader"]].T).toarray()[0, 0])
            if sim >= best_s:
                best, best_s = gi, sim
        if best < 0:
            groups.append({"leader": i, "members": [i]})
            member_group[i] = len(groups) - 1
        else:
            groups[best]["members"].append(i)
            member_group[i] = best
    formed_at = {gi: g["members"][2] for gi, g in enumerate(groups) if len(g["members"]) >= 3}

    def campaign_units(key):
        units = {}
        for i, r in enumerate(te):
            k = key(i, r)
            if k is not None:
                units.setdefault(k, []).append(i)
        return {k: v for k, v in units.items() if len(v) >= 3}

    def early(units):
        stats = []
        for k, ix in units.items():
            first = ix[0]
            # covered = the message sits in a group that has formed by the time that message arrives
            covered = [member_group[i] in formed_at and formed_at[member_group[i]] <= i for i in ix]
            first_cov = next((i for i, c in zip(ix, covered) if c), None)
            before = sum(1 for i, c in zip(ix, covered) if first_cov is None or i < first_cov)
            stats.append({"first_flagged": bool(flagged[first]), "formed": first_cov is not None,
                          "covered_on_arrival": bool(covered[0]),
                          "messages_before_formation": before, "share_before_formation": before / len(ix),
                          "hours_to_formation": max(0.0, (ts(te[first_cov]) - ts(te[first])) / 3600) if first_cov is not None else None})
        if not stats:
            return {"campaigns": 0}
        h = [s["hours_to_formation"] for s in stats if s["hours_to_formation"] is not None]
        return {"campaigns": len(stats),
                "first_message_flagged_novel_rate": round(float(np.mean([s["first_flagged"] for s in stats])), 4),
                "formed_rate": round(float(np.mean([s["formed"] for s in stats])), 4),
                "covered_on_arrival_rate": round(float(np.mean([s["covered_on_arrival"] for s in stats])), 4),
                "median_messages_before_formation": float(np.median([s["messages_before_formation"] for s in stats])),
                "median_share_of_campaign_before_formation": round(float(np.median([s["share_before_formation"] for s in stats])), 4),
                "median_hours_to_formation": round(float(np.median(h)), 2) if h else None}
    novelA = campaign_units(lambda i, r: r["near_dup_cluster"] if gtA[i] else None)
    novelC = campaign_units(lambda i, r: ac[i]["campaign_id"] if gtC[i] else None)
    res["early_signal"] = {
        "procedure": "Stream test messages in time order; messages flagged by D1 (novelty > tau) join an emerging group if cosine >= 0.5 to its first message, else start one; a group 'forms' at its 3rd member.",
        "emerging_groups": len(groups), "formed_groups": len(formed_at),
        "known_message_false_flag_rate": round(float(flagged[~gtA].mean()), 4),
        "novel_campaigns_GT_A_with_3plus_messages": early(novelA),
        "novel_campaigns_GT_C_with_3plus_messages": early(novelC)}
    for k in ("A", "B", "C"):
        r_ = res["results"][f"GT_{k}"]
        print(f"  E4 GT-{k}: D1 AUROC {r_['D1_knn']['auroc']} flagR {r_['D1_knn']['flag_recall']} FPR {r_['D1_knn']['flag_fpr_on_known']} | "
              f"D2 AUROC {r_['D2_campaign_detector']['auroc']} flagR {r_['D2_campaign_detector']['flag_recall']} FPR {r_['D2_campaign_detector']['flag_fpr_on_known']}")
    K.save_artifact({"vectorizer": vec, "svd": svd, "detector": det, "tau": tau}, "e4", "novelty_detectors",
                    {"task": "novel campaign detection", "split": "sp24_temporal_v1", "provenance": res["provenance"]})
    return res


EXPS = {"e0": e0, "e1": e1, "e2": e2, "e3": e3, "e4": e4}


def main() -> int:
    K.seed_all()
    import torch
    torch.set_num_threads(2)
    for exp in sys.argv[1:] or list(EXPS):
        t0 = time.time()
        print(f"== {exp}")
        r = EXPS[exp]()
        r["environment"] = K.environment()
        r["runtime_seconds"] = round(time.time() - t0, 1)
        print(f"   wrote {K.write_result(exp, r)} in {r['runtime_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
