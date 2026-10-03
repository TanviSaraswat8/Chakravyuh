# Real-data experiments E0–E4 (CPU)

**Track: REAL PUBLIC DATA.** No simulator data, PaySim, LLM-generated data or synthetic Hindi/Hinglish is used in any metric here. The one exception is the shipped synthetic-trained tagger, evaluated zero-shot and labelled **SYNTHETIC-TRAINED** wherever it appears.

**What these results are not:**
- Not session, UPI or payee detection: every experiment scores single messages.
- Not Hindi or Hinglish capability.
- Not real-world deployment validation.

Run on 2026-10-03 at code commit `74ba971` (governance), with the frozen security baseline `0e64412` unchanged. Raw JSON is in `experiments/real/results/e{0..4}.json`, and every trained model has a manifest in `experiments/real/manifests/`.

## Setup

| Item | Value |
|---|---|
| Hardware | Intel Xeon @ 2.10 GHz, **2 vCPUs**, 8 GB RAM, no GPU; torch threads = 2 |
| Software | Python 3.13, scikit-learn 1.9.1, torch 2.14.1, numpy 2.5.3, ftfy 6.3.1 |
| Seed | 13 (all models, splits, bootstrap) |
| Runtime | E0 12 s · E1 1,208 s (1,141 s of it the from-scratch transformer) · E2 53 s · E3 89 s · E4 144 s |

### Data (versions and SHA-256 of raw files)

| Dataset | Version | Raw file SHA-256 | Processed file (msg-v1) SHA-256 |
|---|---|---|---|
| imc25_smishing | git a6175560 (2025-09-12) | final_dataset_output.csv `1bbd1e9e…a9a64`; time_day.csv `a0f9afb7…40b11` | `ca5c4334…3d702` |
| sp24_gateway_phishing | git a4f18ced (2025-12-01) | phishing_messages.csv `d125c394…0f230`; phishing_campaigns.csv `f23a5603…600a5` | `9f7f96d2…fc1da` |
| india_spam_sms_junioralive | git 09137cc6 (2024-09-06) | spam_ham_india.csv `e6a28126…a79f3` | `213cc72f…19b9e` |

Full digests are in `data/registry/*.json` and in each result file's `provenance` block.

**Not used:**
- **MOZ-Smishing:** UNSUPPORTED. It isn't acquired (needs a local download) and its dataset licence is unresolved.
- **UCI SMS Spam:** only a third-party mirror is on disk, which is audit-only.

### Splits (leakage-safe; no random splits)

| Split | Definition | SHA-256 |
|---|---|---|
| `imc25_group_v1` | whole near-duplicate clusters (MinHash Jaccard ≥ 0.8) per side, 70/10/20 | `7bfeb0cb…c5cb0` |
| `india_spam_sms_junioralive_group_v1` | same grouping | `29231a95…c8ba` |
| `sp24_temporal_v1` | train < 2023-05-04T23:41Z ≤ val < 2023-05-11T14:49Z ≤ test; test marked seen/novel by cluster | `1928e4b5…f817d5` |

E3 also drops every test message that is a near-duplicate of any training or validation message, recomputed on the exact text variant the model sees. That removed 352 messages (masked variant) and 518 (clean variant) from the in-distribution test, plus 26–27 from S&P'24.

### Preprocessing and text variants
- **masked:** the shared msg-v1 masking. URLs, e-mails, UPI IDs and digit runs become `<URL>/<EMAIL>/<VPA>/<NUM>`; source mask tokens such as IMC'25's `<NAMED_ENTITY>` become `<MASK>`.
- **stripped:** masked, with every placeholder token removed.
- **clean:** mojibake repaired with ftfy, then masked, then stripped. In addition, 35 India records that are chat-export placeholders ("image omitted", "Contact card omitted") are excluded as non-SMS.

### Models (all trained from scratch on the named splits)

| Model | Features | Classifier | Hyperparameters (selected on the validation split) |
|---|---|---|---|
| rules | keyword lexicons in `chakravyuh/realdata/expmodels.py` (English plus some es/nl/fr/de terms) | most keyword hits wins, else a default class | none |
| tfidf_lr | word 1–2-gram TF-IDF, min_df 2, sublinear, ≤200k features | LogisticRegression, class_weight=balanced (one-vs-rest for multi-label) | C ∈ {0.5, 2, 8} → E1 C=8; E2 C=2; E3 masked C=8, clean C=8 |
| tfidf_svm | same | LinearSVC, balanced; probabilities from sigmoid calibration fitted on val (used for ECE and thresholds only) | C ∈ {0.1, 0.5, 2} → E1 0.5; E2 0.1; E3 masked 0.5, clean 2 |
| chakravyuh_tagger_arch | char_wb 2–5 TF-IDF, 60k features: **identical to the shipped `TacticTagger`** | one-vs-rest LogisticRegression, C=4, balanced | fixed (the shipped configuration) |
| char_transformer_scratch | lower-cased characters, vocabulary 2,500, max 200 chars | 2-layer Transformer encoder (d=96, 4 heads, FF 192, dropout 0.1), mean pooling | AdamW lr 2e-3, weight decay 0.01, batch 64, 5 epochs, best epoch on val. E1 only (see below) |
| shipped synthetic tagger (**SYNTHETIC-TRAINED**) | as shipped, SHA-256 checked through `Engine.load` | trained only on simulator data | zero-shot, on the clean text variant |

**Latency:** one message per call on the CPU, feature extraction included; median and 95th percentile over 300 test messages.

---

## E0 — Source artefact check

**Label:** REAL PUBLIC DATA.

**Question:** can a classifier tell which *dataset* a message came from? If it can, a scam-vs-legit score on mixed sources partly measures the source, not the scam.

**Setup:** 3-way source classification (IMC'25 / India SMS / S&P'24), with each source capped at 6,000 train and 1,500 test messages, on group/temporal splits. Chance balanced accuracy is 0.333.

| Features | Balanced accuracy | Recall IMC'25 / India / S&P'24 |
|---|---|---|
| raw text | 0.964 | 0.959 / 0.943 / 0.990 |
| masked text | **0.970** | 0.963 / 0.952 / 0.994 |
| stripped (placeholders removed) | 0.907 | 0.888 / 0.866 / 0.968 |
| clean (+ mojibake repair, export artefacts removed) | 0.918 | 0.891 / 0.897 / 0.968 |
| **artefact features only** (placeholder counts, length, upper-case ratio: no words) | **0.884** | 0.825 / 0.833 / 0.993 |

**Controlled same-label probe.** IMC'25 "spam" (1,710) against India promotional "spam" (745): the same label, different sources, group split.

| Features | Balanced accuracy |
|---|---|
| masked | 0.989 |
| stripped / clean | 0.938 |
| clean, IMC'25 English only | 0.903 |

**Result:**
1. **Masking itself is a source artefact.** Placeholder counts alone identify the source at 0.884. In particular, `<MASK>` (IMC'25's named-entity masking) occurs essentially only in IMC'25.
2. Two further artefacts appear in the top features:
   - mojibake (`Ã¢Â€Â™`) in 176 India records; ftfy repairs 170 of them;
   - WhatsApp-export placeholders ("image omitted") in 35 India records.
3. **Mitigation:** the clean variant lowers source accuracy (0.970 → 0.918; same-label 0.989 → 0.938) but **does not remove source identity**. What remains is real content difference: Indian operator brands (Airtel, Vi), personal-chat words, and language (35% of IMC'25 test messages are non-English).
4. **Consequence:** E3's in-distribution numbers are optimistic, and E3 is reported on both variants. E3 confirms the artefact directly: with masked text, S&P'24 recall collapses (below).

---

## E1 — IMC'25 scam type (8 classes)

**Label:** REAL PUBLIC DATA · WEAKLY LABELLED. The labels are GPT-4o's; against humans, κ = 0.93 on 150 English messages.

- **Split:** `imc25_group_v1` (train 23,651 / val 3,378 / test 6,759; 81 unlabelled records dropped). Masked text.
- **Test class distribution:**

  | banking | others | delivery | government | telecom | spam | wrong number | hey mum/dad |
  |---|---|---|---|---|---|---|---|
  | 2,956 | 1,388 | 784 | 693 | 466 | 355 | 67 | 50 |

| Model | Macro-F1 | Accuracy | ECE (top-label) | Macro-F1 English / non-English | Latency p50 / p95 (ms) | Train (s) |
|---|---|---|---|---|---|---|
| rules | 0.494 | 0.635 | — | 0.596 / 0.295 | 0.03 / 0.14 | 0 |
| tfidf_lr | **0.776** | 0.810 | **0.033** | 0.815 / 0.608 | 0.60 / 0.85 | 38 |
| tfidf_svm | 0.771 | 0.817 | 0.043 | 0.809 / 0.608 | 0.64 / 0.92 | 8 |
| chakravyuh_tagger_arch | 0.772 | **0.818** | 0.130 | 0.800 / **0.663** | 1.92 / 2.71 | 15 |
| char_transformer_scratch | 0.473 | 0.507 | 0.092 | 0.485 / 0.362 | 2.10 / 2.61 | 1,141 |

**Per-class F1** (support in brackets):

| Class | rules | tfidf_lr | tfidf_svm | tagger_arch |
|---|---|---|---|---|
| banking (2,956) | 0.811 | 0.911 | 0.915 | 0.916 |
| delivery (784) | 0.811 | 0.909 | 0.911 | 0.915 |
| government (693) | 0.459 | 0.809 | 0.804 | 0.806 |
| telecom (466) | 0.495 | 0.774 | 0.775 | 0.767 |
| wrong number (67) | 0.388 | 0.662 | 0.633 | 0.662 |
| hey mum/dad (50) | 0.316 | 0.947 | 0.911 | 0.889 |
| others (1,388) | 0.466 | 0.622 | 0.634 | 0.655 |
| spam (355) | 0.205 | 0.577 | 0.584 | 0.564 |

**tfidf_lr, per class:**

| Class | Precision | Recall |
|---|---|---|
| banking | 0.921 | 0.901 |
| delivery | 0.925 | 0.893 |
| government | 0.819 | 0.798 |
| telecom | 0.747 | 0.803 |
| wrong number | 0.627 | 0.702 |
| hey mum/dad | 1.000 | 0.900 |
| others | 0.609 | 0.636 |
| spam | 0.568 | 0.586 |

**Confusion matrix, tfidf_lr** (rows = true, columns = predicted):

| | banking | delivery | gov. | telecom | wrong # | mum/dad | others | spam |
|---|---|---|---|---|---|---|---|---|
| banking | 2662 | 15 | 29 | 25 | 0 | 0 | 211 | 14 |
| delivery | 10 | 700 | 1 | 6 | 1 | 0 | 61 | 5 |
| government | 17 | 6 | 553 | 12 | 2 | 0 | 94 | 9 |
| telecom | 20 | 2 | 3 | 374 | 0 | 0 | 57 | 10 |
| wrong number | 0 | 0 | 0 | 0 | 47 | 0 | 19 | 1 |
| hey mum/dad | 1 | 0 | 0 | 0 | 1 | 45 | 3 | 0 |
| others | 172 | 31 | 85 | 76 | 22 | 0 | 883 | 119 |
| spam | 7 | 3 | 4 | 8 | 2 | 0 | 123 | 208 |

Full confusion matrices for every model are in `e1.json`.

**Reading:**
- The three linear text models are statistically close (macro-F1 0.771–0.776).
- Most errors involve the vague "others" and "spam" classes, the same boundary the GPT-4o labeller is least consistent on.
- Non-English macro-F1 is about 0.2 lower.
- The from-scratch transformer underfits on 2 CPUs (best val macro-F1 0.465 after 5 × ~220 s). It was **not** run in E2/E3: the CPU cost isn't reasonable for that result, and a *pretrained* small transformer belongs on GPU.
- The shipped tagger has no scam-type head, so it isn't applicable to E1.

---

## E2 — Lure tagging (7 labels)

**Label:** REAL PUBLIC DATA · **WEAKLY LABELLED.** The lures were assigned by GPT-4o (Stajano & Wilson typology); against humans, κ = 0.70 on 150 English messages. **These scores measure agreement with GPT-4o, not accuracy against human ground truth.**

- **Split:** `imc25_group_v1`, scam messages with at least one lure (train 21,576 / val 3,059 / test 6,154).
- **Test prevalence:**

  | authority | time/urgency | distraction | need and greed | kindness | dishonesty | herd |
  |---|---|---|---|---|---|---|
  | 5,170 | 4,980 | 1,846 | 1,135 | 133 | 36 | 28 |

| Model | Micro-F1 | Macro-F1 | Latency p50 (ms) |
|---|---|---|---|
| rules | 0.410 | 0.274 | 0.02 |
| tfidf_lr (threshold 0.5) | **0.810** | 0.543 | 1.49 |
| tfidf_svm | 0.801 | 0.544 | 1.83 |
| chakravyuh_tagger_arch | 0.806 | **0.567** | 1.71 |
| shipped synthetic tagger, zero-shot (**SYNTHETIC-TRAINED**; 5 mapped lures only) | 0.393 | 0.179 | 2.55 |

**Per-label precision / recall:**

| Label (support) | tfidf_lr | tagger_arch | synthetic tagger |
|---|---|---|---|
| authority (5,170) | 0.936 / 0.845 | 0.940 / 0.843 | 0.984 / 0.190 |
| time/urgency (4,980) | 0.947 / 0.853 | 0.949 / 0.848 | 0.897 / 0.370 |
| distraction (1,846) | 0.455 / 0.563 | 0.450 / 0.579 | — |
| need and greed (1,135) | 0.686 / 0.779 | 0.651 / 0.773 | 0.638 / 0.026 |
| kindness (133) | 0.556 / 0.707 | 0.538 / 0.797 | 0 / 0 |
| herd (28) | 0.130 / 0.214 | 0.186 / 0.393 | 0 / 0 |
| dishonesty (36) | 0 / 0 | 0.105 / 0.056 | — |

**Per-label confusion, tfidf_lr (TP / FP / FN / TN):**

| Label | TP | FP | FN | TN |
|---|---|---|---|---|
| authority | 4,367 | 297 | 803 | 687 |
| time/urgency | 4,248 | 240 | 732 | 934 |
| distraction | 1,040 | 1,246 | 806 | 3,062 |
| need and greed | 884 | 405 | 251 | 4,614 |
| kindness | 94 | 75 | 39 | 5,946 |
| herd | 6 | 40 | 22 | 6,086 |
| dishonesty | 0 | 10 | 36 | 6,108 |

**Reading:**
- authority, urgency and greed are reproducible from text.
- distraction is not (F1 ≈ 0.50).
- herd and dishonesty are too rare and too noisy to learn: 28 and 36 test examples, with near-zero F1.
- **The synthetic-trained tagger transfers poorly to real messages** (recall 0.03–0.37 on the mapped lures).

---

## E3 — Scam vs legitimate vs promotional

**Label:** REAL PUBLIC DATA, with an **EXTERNAL TEST** on S&P'24.

**Data and split:**
- Scams: IMC'25 scam class from `imc25_group_v1`. Its "spam" class is excluded.
- Legitimate and promotional: India SMS from `india_spam_sms_junioralive_group_v1`.
- **Class sizes:** train 22,466 scam / 1,044 legit / 507 promo; test (before purge) 6,404 / 310 / 144.
- **This is not a balanced or representative problem. Do not read the high scam precision as real-world precision:** scams are 93% of the test set.

**Binary metrics:** scam is the positive class. FPR is reported separately for legitimate and promotional messages, with 95% bootstrap confidence intervals.

### Argmax decision

| Variant | Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | ECE | FPR legit [95% CI] | FPR promo [95% CI] | FNR | S&P'24 recall (EXTERNAL) | p50 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| masked | rules | 0.996 | 0.312 | 0.475 | 0.959 | 0.695 | 0.427 | 0.013 [0.003, 0.026] | 0.021 [0, 0.049] | 0.689 | 0.005 | 0.01 |
| masked | tfidf_lr | 0.994 | 0.987 | 0.990 | 0.9997 | 0.996 | 0.022 | 0.091 [0.062, 0.124] | 0.063 [0.028, 0.106] | 0.013 | **0.026** | 0.61 |
| masked | tfidf_svm | 0.991 | 0.993 | 0.992 | 0.9997 | 0.996 | 0.006 | 0.147 [0.107, 0.186] | 0.070 [0.035, 0.113] | 0.007 | 0.855 | 1.01 |
| masked | tagger_arch | 0.995 | 0.989 | 0.992 | 0.9998 | 0.998 | 0.026 | 0.085 [0.055, 0.117] | 0.014 [0, 0.035] | 0.011 | **0.012** | 1.20 |
| clean | rules | 0.996 | 0.312 | 0.475 | 0.959 | 0.695 | 0.426 | 0.013 | 0.021 | 0.688 | 0.005 | 0.01 |
| clean | tfidf_lr | 0.990 | 0.971 | 0.981 | 0.9985 | 0.983 | 0.038 | 0.122 [0.089, 0.158] | 0.134 [0.085, 0.190] | 0.029 | **0.997** | 0.66 |
| clean | tfidf_svm | 0.985 | 0.990 | 0.987 | 0.9981 | 0.981 | 0.012 | 0.214 [0.168, 0.260] | 0.169 [0.113, 0.232] | 0.010 | 0.999 | 0.58 |
| clean | tagger_arch | 0.990 | 0.972 | 0.981 | 0.9989 | 0.987 | 0.044 | 0.128 [0.089, 0.164] | 0.120 [0.070, 0.176] | 0.028 | 0.998 | 1.07 |
| clean | shipped synthetic tagger (**SYNTHETIC-TRAINED**, zero-shot) | 0.937 | 0.742 | 0.828 | 0.942 | 0.557 | 0.282 | **0.605** [0.549, 0.658] | **0.789** [0.718, 0.852] | 0.258 | 0.19 | 2.73 |

**Operating point "legitimate FPR ≤ 1% on validation":** the threshold on p(scam) is set on only **133 validation legitimate messages**, so it is coarse.

| Variant | Model | Threshold | Recall | FPR legit | FPR promo | S&P'24 recall (EXTERNAL) |
|---|---|---|---|---|---|---|
| masked | tfidf_lr | 0.823 | 0.959 | 0.010 | 0.014 | 0.006 |
| masked | tagger_arch | 0.772 | 0.961 | 0.003 | 0.014 | 0.001 |
| clean | tfidf_lr | 0.952 | 0.820 | 0.016 | 0.014 | 0.254 |
| clean | tfidf_svm | 0.988 | 0.812 | 0.016 | 0.049 | 0.601 |
| clean | tagger_arch | 0.956 | **0.768** | **0.003** | **0.014** | **0.974** |
| clean | synthetic tagger | 0.922 | 0.080 | 0.040 | 0.063 | 0.000 |

**3-class confusion, clean tfidf_lr** (rows true scam / legit / promo; columns predicted):

| | scam | legit | promo |
|---|---|---|---|
| scam | 5,722 | 106 | 66 |
| legit | 37 | 267 | 0 |
| promo | 19 | 1 | 122 |

Every model's matrix is in `e3.json`.

**Subset recall** (argmax, clean tfidf_lr):

| IMC'25 English | IMC'25 non-English | IMC'25 sent from Indian networks (n=548) |
|---|---|---|
| 0.971 | 0.970 | 0.991 |

These are **recall only**: there are no Indian scam negatives.

**Reading:**
1. **The source artefact is real and decisive.** On masked text, logistic regression and the tagger architecture look near-perfect in-distribution (F1 0.99), but catch only **1–3% of S&P'24 scams**. They learned "contains `<MASK>`" (IMC'25's masking) rather than scam content. On the clean variant the same models catch 99.7–99.8% of S&P'24.
2. **Even the clean result is not proof of scam detection.** All negatives come from one Indian source, and E0 shows that source is still about 90% identifiable. "Not Indian-telecom-style" may be part of what the model calls scam. The proper control is legitimate messages from a different source, such as the official UCI file once you register it. MOZ-Smishing (UNSUPPORTED here) would add an out-of-domain test.
3. **Alert fatigue:**
   - At argmax, 12–21% of legitimate and 12–17% of promotional India messages are flagged as scam.
   - At a validation-set threshold, legitimate FPR drops to 0.3–1.6%, at the cost of recall (0.77–0.82 on IMC'25).
   - The confidence intervals are wide (n = 304 legitimate, 142 promotional).
4. The synthetic-trained tagger flags 60% of legitimate and 79% of promotional messages. **Simulator training does not transfer to real SMS.**

---

## E4 — New-campaign detection (S&P'24)

**Label:** REAL PUBLIC DATA, temporal test. These are gateway messages, not victim sessions.

- **Split:** `sp24_temporal_v1` (train 47,620 / val 6,801 / test 13,608).
- **Embeddings:** character 3–5 TF-IDF fitted on training text only, plus SVD-128 for the clustering detector.

**Ground truths for "novel":**

| | Definition | Known / novel in test |
|---|---|---|
| A | near-duplicate cluster never seen in train. This is the split's own definition, so **partly circular** with a text-similarity detector | 3,084 / 10,524 |
| B | exact normalised template never seen in train | 57 / 13,551 |
| C | the authors' campaign (matched by template + time for 86% of messages) started after the training cut. **Independent of our clustering** | 20 / 11,683 |

**Detectors:**
- **D1, nearest-neighbour novelty:** 1 − max cosine to any training message. It flags when the score exceeds τ = 0.260, the 95th percentile on validation messages whose template appears in train.
- **D2, the current `CampaignDetector` algorithm:** HDBSCAN (min cluster 5) on training embeddings gives 254 clusters (14.7% noise) as prototypes. A message is "unknown" if its distance exceeds δ = 0.043, the 97% quantile.

| Ground truth | Detector | AUROC [95% CI] | Flag recall | Flag FPR on known |
|---|---|---|---|---|
| A | D1 | 0.999 [0.999, 1.000] | 0.997 | 0.001 |
| A | D2 | 0.990 [0.986, 0.993] | 0.998 | 0.017 |
| B (57 known) | D1 | 0.978 [0.952, 0.994] | 0.774 | 0.018 |
| B (57 known) | D2 | 0.589 [0.484, 0.686] | 0.777 | 0.597 |
| C (20 known) | D1 | 0.999 [0.999, 1.000] | 0.883 | 0.000 |
| C (20 known) | D2 | **0.299** [0.137, 0.476] | 0.887 | **0.850** |

**Cluster agreement with the authors' campaign IDs** (test period, mapped messages):

| Clustering | ARI | NMI | Homogeneity | Completeness | Clusters vs authors' campaigns |
|---|---|---|---|---|---|
| HDBSCAN on test messages | 0.026 | 0.907 | 0.830 | 1.000 | 3,921 vs 7,162 |
| our near-duplicate clusters | 0.001 | 0.348 | 0.211 | 1.000 | 360 vs 7,162 |

Text clusters never split an authors' campaign (completeness 1.0). They do merge many of them: the authors split one text template into many campaigns by URL and time, and the median campaign lasts under a day. Low ARI reflects that difference in granularity, not random clustering.

**Temporal behaviour:**
- The share of novel test traffic rises fast. D1 flags 10–38% of messages on the first two test days and 97–100% from day 4 (2023-05-14), with GT-A AUROC ≥ 0.999 on every day that has both classes.
- By the authors' definition, 99.8% of test-period messages already belong to campaigns that started after training. In this data, "new campaign" is the normal case.

**Early signal (streaming):**
- **Procedure:** test messages are processed in time order. Flagged messages join an emerging group if cosine ≥ 0.5 to its first message; a group "forms" at its third member. 112 emerging groups, 50 formed; the false-flag rate on GT-A-known messages is 0.06%.
- **Novel GT-A clusters with ≥ 3 test messages (71):**
  - 95.8% have their first message flagged as novel.
  - 95.8% form a group.
  - Median 1 message (20% of the campaign) arrives before formation; median 0.04 h to formation.
- **Novel authors' campaigns with ≥ 3 messages (221):**
  - 79.6% first-message flagged.
  - **72.4% are already covered on arrival** by a group formed from an earlier near-identical campaign. They re-send known text with a new URL.

**Reading:**
1. Simple nearest-neighbour novelty separates seen from unseen text almost perfectly here. With A that is partly circular (similar notions of similarity). With B and C the known sets are tiny (57 and 20), so the confidence intervals, not the point estimates, are what to read.
2. **Failure:** the current `CampaignDetector` prototype approach (built for family-level session embeddings) does **not** transfer to message-level campaign novelty. It flags 60–85% of known-template messages as unknown under B and C, because SVD/HDBSCAN prototypes plus a 97% radius are too coarse.
3. **Early signal: yes, measurably.** Most new campaigns are flagged from their first message and grouped within the first few messages. Many "new" campaigns by URL are text re-runs, and those are caught on arrival.
4. **Limits:** gateway numbers receive spam from many senders. This is campaign *text* novelty, not victim impact, and there are no outcomes.

---

## Leakage checks applied

- Grouped and temporal splits only; no random splits.
- Test near-duplicates of training data are purged per variant and per model input (E3), and E2/E1 use cluster-grouped splits.
- In E4, the TF-IDF, SVD, HDBSCAN prototypes and τ are fitted on train/val only. Test messages are never seen during fitting, and the streaming simulation runs in time order.
- E0's artefact check is applied before any detection claim.
- No synthetic data appears in any real-data metric. The shipped synthetic tagger is evaluated only, never trained further, and labelled.

## Limitations

- **Labels:** GPT-4o weak labels (E1/E2); URL-reputation labels with promotional noise (S&P'24).
- **Negatives:** small and single-source (India SMS, 1,522 legitimate before splitting; provenance undocumented).
- **Language:** English-dominant; Hindi/Hinglish not evaluated.
- **Scope:** single messages only: no sessions, payees, payments or outcomes.
- **Statistical power:** small-class metrics (wrong number, hey mum/dad, herd, dishonesty, legitimate/promotional FPR) have wide intervals.
- **Transformer:** the from-scratch transformer is not a fair test of transformers. Pretrained models need a GPU and Hugging Face access.
- **Not validated:** MOZ-Smishing and the official UCI file are not yet available, so unseen-source legitimate FPR is **not yet measured**.

## Reproduce

```bash
make data-real                              # fetch pinned datasets (SHA-256 checked)
python scripts/validate_real_dataset.py --all
python scripts/prepare_real_splits.py       # processed msg-v1 + leakage-safe splits
pip install -r backend/requirements-data.txt
python scripts/run_real_experiments.py e0 e1 e2 e3 e4    # ~25 min on 2 vCPUs (E1's transformer ~19 min)
```

Results land in `experiments/real/results/`. Trained models go to `experiments/real/artifacts/` (git-ignored; pickles are local experiment outputs that the API never loads). Their manifests are in `experiments/real/manifests/` with the SHA-256, configuration, data and split hashes, and the code commit.
