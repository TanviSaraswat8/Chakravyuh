# Cross-source validation E5–E7

**Track: REAL PUBLIC DATA.** These are frozen E3 models: nothing was retrained on UCI or S&P'24. Every source is reported separately, with no merged headline.

**Out of scope:**
- No synthetic data in any metric. The shipped synthetic-trained tagger appears only as a labelled zero-shot reference.
- No Hindi/Hinglish, UPI, session, payee or victim-outcome claims.
- Not real-world deployment validation.

Run on 2026-10-03, code commit `a5f606c` plus this commit. Results are in `experiments/real/results/e5.json`, `e6.json` and `e7.json`; the runner is `scripts/run_cross_source.py`.

## Official UCI SMS Spam Collection (new independent source)

| Field | Value |
|---|---|
| Official source | UCI Machine Learning Repository, dataset 228: https://archive.ics.uci.edu/dataset/228/sms+spam+collection; zip `https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip` |
| DOI / version | 10.24432/C5CC84; donated 2012-06-21; zip members `SMSSpamCollection` (477,907 bytes, dated 2011-03-15) and `readme` |
| Licence | CC BY 4.0. The UCI page states: "This dataset is licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) license." |
| Citation | Almeida, T. & Hidalgo, J. (2011). SMS Spam Collection. UCI ML Repository. doi:10.24432/C5CC84 |
| Download and provenance | UCI is blocked from the build environment and from the linked laptop's sandbox (HTTP 403). The project owner downloaded the zip in a browser and supplied it as a chat upload on 2026-10-03. The origin is therefore **attested by the owner, not independently verified**. Registered with `scripts/register_official_uci.py`. |
| SHA-256 | zip `1587ea43e58e82b14ff1f5425c88e17f8496bfcdb67a583dbff9eefaf9963ce3`; SMSSpamCollection `7d039a24a6083ed9ef0f806ebad56bbb976e3aeb8de05669173bfdc4996c239d`; readme `8753cd2d3cab68f80c8257851b8c2037778c267f55accb6fd1b5a2e32d36a84e` |
| Integrity | `SMSSpamCollection` is **byte-identical** to the third-party mirror used in the Phase 1 audit, so earlier overlap findings hold |
| Sample count / schema | 5,574 lines, `label<TAB>text`; ham 4,827, spam 747 |
| Label mapping | ham → `legit`. spam → `spam`, never `scam`: UCI spam mixes premium-rate prize scams with marketing, so only a *flag rate* is reported for it |
| Preprocessing | the same msg-v1 adapter and the same **clean** variant as E3 (ftfy repair, shared masking, placeholders stripped) |
| Role | **evaluation and threshold calibration only.** Never training data for these models. E7 splits UCI ham 50/50 by near-duplicate group: calibration half n=2,401, evaluation half n=2,402 |
| Raw data | not committed (`data/real/**/raw/` and `data/incoming/` are git-ignored) |

Re-running `prepare_real_splits.py` after registration left every existing split and processed file byte-identical. Only the `SPLITS.json` index changed, because it gained a `uci_group_v1` entry that E5–E7 do not use.

**Leakage control:** any evaluation message that is a near-duplicate of E3's training or validation text is dropped (clean variant): IMC'25 510, India 8, UCI 24, S&P'24 26.

## E5 — Frozen E3 models on four sources (clean text, the variant E3 recommends)

Decisions: argmax, and the E3 threshold ("legitimate FPR ≤ 1%" chosen on 133 India validation messages). All intervals are bootstrap 95% CIs.

### At argmax

| Model | IMC'25 recall (n=5,894) | India legit FPR (n=304) | India promo FPR (n=142) | **UCI ham FPR (n=4,803)** | UCI spam flag rate (n=747) | S&P'24 recall (n=13,582) |
|---|---|---|---|---|---|---|
| tfidf_lr | 0.971 | 0.122 [0.089, 0.158] | 0.134 | **0.443** [0.429, 0.457] | 0.890 | 0.997 |
| tfidf_svm | 0.990 | 0.214 [0.168, 0.260] | 0.169 | **0.645** [0.631, 0.659] | 0.938 | 0.999 |
| chakravyuh_tagger_arch | 0.972 | 0.128 [0.089, 0.164] | 0.120 | **0.350** [0.337, 0.364] | 0.801 | 0.998 |
| shipped synthetic tagger (SYNTHETIC-TRAINED, p ≥ 0.5) | 0.742 | 0.605 | 0.789 | **0.632** | 0.794 | 0.213 |

### At the E3 threshold (chosen on India validation)

| Model | Threshold | IMC'25 recall | India legit FPR | India promo FPR | **UCI ham FPR** | S&P'24 recall |
|---|---|---|---|---|---|---|
| tfidf_lr | 0.952 | 0.820 | 0.016 | 0.014 | **0.052** [0.046, 0.059] | 0.254 |
| tfidf_svm | 0.988 | 0.812 | 0.016 | 0.049 | **0.082** [0.075, 0.090] | 0.601 |
| chakravyuh_tagger_arch | 0.956 | 0.768 | 0.003 | 0.014 | **0.018** [0.015, 0.022] | 0.974 |

### Cross-source pairs

Each pair is one scam source against one legitimate source. These are pairings, not merged scores, and precision depends on the stated prevalence.

| Model | Pair | Prevalence | PR-AUC | ROC-AUC | ECE | Precision / recall / FPR at E3 threshold |
|---|---|---|---|---|---|---|
| tagger_arch | IMC'25 vs UCI ham | 0.551 | 0.976 | 0.965 | 0.139 | 0.981 / 0.768 / 0.018 |
| tagger_arch | S&P'24 vs UCI ham | 0.739 | 0.994 | 0.992 | 0.088 | 0.994 / 0.974 / 0.018 |
| tagger_arch | IMC'25 vs India legit | 0.951 | 0.999 | 0.988 | 0.048 | 1.000 / 0.768 / 0.003 |
| tfidf_lr | IMC'25 vs UCI ham | 0.551 | 0.963 | 0.950 | 0.173 | 0.951 / 0.820 / 0.052 |
| tfidf_lr | S&P'24 vs UCI ham | 0.739 | 0.966 | 0.929 | 0.081 | 0.933 / 0.254 / 0.052 |
| tfidf_svm | IMC'25 vs UCI ham | 0.551 | 0.943 | 0.935 | 0.259 | 0.924 / 0.812 / 0.082 |
| tfidf_svm | S&P'24 vs UCI ham | 0.739 | 0.961 | 0.925 | 0.149 | 0.954 / 0.601 / 0.082 |

### Masked variant

This is the variant E3 rejected; it is shown for completeness.

| Model | UCI ham FPR at argmax | S&P'24 recall at argmax | S&P'24-vs-UCI ROC-AUC |
|---|---|---|---|
| tfidf_lr | 0.304 | 0.244 | 0.604 |
| tfidf_svm | 0.410 | 0.885 | 0.659 |
| chakravyuh_tagger_arch | 0.191 | 0.010 | **0.265** |

A ROC-AUC of 0.265 means the masked model ranks independent legitimate SMS as *more* scam-like than real S&P'24 scams. That is the masking artefact, measured against an independent source.

**Confusion matrices and latency.** Full 3-class matrices for every model, source and decision are in `e5.json`. For example, tagger_arch on UCI at argmax:

| UCI true label | → scam | → legit | → promo |
|---|---|---|---|
| ham | 1,683 | 3,090 | 30 |
| spam | 598 | 63 | 86 |

Latency p50 / p95 per message: tfidf_lr 0.56 / 0.64 ms; tfidf_svm 1.64 / 2.22 ms (includes the calibrator); tagger_arch 1.37 / 1.79 ms.

**About the SVM calibrator:** E3 didn't persist the SVM's sigmoid calibrator. It was refitted, deterministically, on the identical E3 validation split, and the SVM itself is the frozen artifact. E5's in-distribution numbers reproduce E3 exactly for all three models.

## E6 — Source identification with four sources

**Setup:** text-only classifier (word TF-IDF + logistic regression), grouped splits, each source capped at 4,000 train / 1,000 test (India 1,551 / 454). Chance balanced accuracy is 0.25.

| Features | Balanced accuracy | Recall IMC'25 / India / S&P'24 / UCI |
|---|---|---|
| masked text | 0.939 | 0.961 / 0.852 / 0.989 / 0.953 |
| **clean text** | **0.900** | 0.879 / 0.824 / 0.964 / 0.932 |
| artefact features only (placeholder counts, length, upper-case ratio) | 0.744 | 0.842 / 0.198 / 0.989 / 0.945 |

**Confusion, clean text** (rows true, columns predicted; order IMC'25, India, S&P'24, UCI):

| | IMC'25 | India | S&P'24 | UCI |
|---|---|---|---|---|
| IMC'25 | 879 | 52 | 18 | 51 |
| India | 25 | 374 | 0 | 55 |
| S&P'24 | 22 | 4 | 964 | 10 |
| UCI | 24 | 44 | 0 | 932 |

**Same-label probes** (clean text, group split):

| Probe | Balanced accuracy |
|---|---|
| India legitimate vs UCI legitimate (1,487 vs 4,827) | **0.908** |
| IMC'25 English scams vs S&P'24 scams (6,000 vs 6,000) | **0.878** |

**Result: domain shift is still substantial.** Even two corpora with the *same* label are about 88–91% separable from wording alone. The top features are dialect and era (UCI: "u", "ur", "ü"), operator names (India: Airtel, Vi), stock-tip group chat (India: market, stocks, professor) and gateway boilerplate (S&P'24: optout, login code). This result is reported as measured and was not normalised away.

## E7 — Threshold robustness

**Setup:**
- Frozen E3 clean models.
- Full curves at 27 thresholds (0.05–0.999) are in `e7.json`, each with Wilson 95% CIs.
- **Coverage** is defined as alert volume: the share of all evaluated messages (IMC'25 test + S&P'24 test + India test + UCI ham evaluation half) that are flagged.

### Selected curve points: chakravyuh_tagger_arch

| Threshold | UCI ham FPR [95% CI] | India legit FPR | India promo FPR | IMC'25 recall [95% CI] | S&P'24 recall | Precision (IMC'25 vs UCI eval) | Coverage |
|---|---|---|---|---|---|---|---|
| 0.50 | 0.345 [0.326, 0.364] | 0.125 | 0.120 | 0.971 [0.966, 0.975] | 0.998 | 0.873 | 0.903 |
| 0.70 | 0.168 [0.153, 0.183] | 0.079 | 0.078 | 0.949 | 0.996 | 0.933 | 0.876 |
| 0.90 | 0.050 [0.042, 0.059] | 0.003 | 0.014 | 0.875 | 0.986 | 0.977 | 0.836 |
| 0.95 | 0.023 [0.018, 0.030] | 0.003 | 0.014 | 0.788 [0.777, 0.798] | 0.978 | 0.988 | 0.806 |
| 0.97 | 0.013 [0.009, 0.018] | 0.000 | 0.014 | 0.702 [0.691, 0.714] | 0.931 | 0.993 | 0.753 |
| 0.98 | 0.007 [0.004, 0.011] | 0.000 | 0.014 | 0.624 | **0.450** | 0.996 | 0.439 |
| 0.99 | 0.002 [0.001, 0.005] | 0.000 | 0.007 | 0.468 | 0.147 | 0.998 | 0.213 |

### tfidf_lr, for contrast

| Threshold | UCI ham FPR | IMC'25 recall | S&P'24 recall |
|---|---|---|---|
| 0.90 | 0.116 | 0.888 | 0.896 |
| 0.95 | 0.053 | 0.824 | **0.255** |
| 0.99 | 0.009 | 0.568 | 0.239 |

S&P'24 recall falls off a cliff between 0.90 and 0.95, because most S&P'24 scores sit in a narrow band.

### Threshold selection ("legitimate FPR ≤ 1%")

The rule picks the smallest threshold that flags at most 1% of the calibration messages; ties are handled. Uncertainty comes from 500 bootstrap resamples of the calibration set.

| Model | Calibration set | Threshold [95% CI] | UCI ham *eval* FPR [CI over bootstrap thresholds] | India legit FPR | India promo FPR | IMC'25 recall [CI] | S&P'24 recall |
|---|---|---|---|---|---|---|---|
| tagger_arch | UCI ham calibration half (n=2,401) | 0.966 [0.957, 0.972] | 0.014 [0.011, 0.020] | 0.000 | 0.014 | 0.731 [0.687, 0.765] | 0.961 |
| tagger_arch | India val legit (n=133) | 0.956 (CI degenerate: tied scores) | 0.021 | 0.003 | 0.014 | 0.768 | 0.974 |
| tfidf_lr | UCI ham calibration half | 0.988 [0.984, 0.990] | 0.011 [0.009, 0.015] | 0.000 | 0.014 | 0.610 [0.572, 0.656] | 0.241 |
| tfidf_lr | India val legit | 0.952 | 0.051 | 0.016 | 0.014 | 0.821 | 0.254 |
| tfidf_svm | UCI ham calibration half | 0.998 [0.997, 0.998] | 0.014 [0.007, 0.021] | 0.000 | 0.014 | 0.328 [0.274, 0.442] | 0.232 |
| tfidf_svm | India val legit | 0.988 | 0.090 | 0.016 | 0.049 | 0.812 | 0.601 |

**Result:**
1. **The 133-message India threshold is not reliable.**
   - It understates false alarms on another legitimate source by about 2× (tagger_arch: 2.1% vs the 1% target) to 9× (SVM: 9.0%).
   - Its bootstrap CI collapses to a single value because of tied scores. That is a sign of too little data, not of stability.
2. With a threshold calibrated on 2,401 independent legitimate messages, the 1% target holds on the held-out half (1.1–1.4%). It costs recall: IMC'25 scam recall falls to 0.73 (tagger_arch), 0.61 (LR) and 0.33 (SVM).
3. Only the character n-gram tagger architecture keeps S&P'24 recall high (0.96) at a 1% legitimate FPR. The word-TF-IDF models lose most S&P'24 recall at any threshold that controls false alarms.
4. Between 0.97 and 0.98, small threshold changes swing S&P'24 recall from 0.93 to 0.45. **A single threshold is not robust.** Report a range and recalibrate per deployment population.

## Cross-source false alarms: summary

Legitimate SMS from an unseen source are flagged at **35–64%** with the default decision, and at **1.8–8.2%** with the E3 threshold. Only a threshold calibrated on independent legitimate data reaches about 1%, at a recall cost. India promotional FPR stays at 1.4% across calibrated thresholds, but rests on only 142 messages (CI up to about 5%).

## Conclusions

- **E3's in-distribution numbers do not transfer.** The models learned real scam signal: cross-source ranking ROC-AUC is 0.93–0.99, with the tagger architecture best at 0.965 and 0.992. But their probabilities and thresholds are source-specific.
- **The legitimate side is the weak link.** Two small, old or single-region legitimate corpora cannot represent "normal SMS".
- These are single-message results on public data; they are not deployment validation.

## Reproduce

```bash
python scripts/register_official_uci.py data/incoming/smsspamcollection.zip   # official zip; prints SHA-256s
python scripts/prepare_real_splits.py                                         # existing splits stay byte-identical
python scripts/run_cross_source.py e5 e6 e7                                   # ~2 min on 2 vCPUs
```
