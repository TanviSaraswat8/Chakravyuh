# Real-data training plan

Status: E0–E4 (CPU) approved and run on 2026-10-03; results in `REAL_EXPERIMENT_RESULTS.md`. E5 (Sentinel, GPU) is not started and awaits approval.

## Scope

- Real-data track only. Simulator results stay on the synthetic track and are never merged with these.
- Every report is stamped `track: REAL` and names its split ids.
- No experiment below claims superiority before it is measured. No result here is "real-world validated" deployment performance: they are held-out results on public datasets with known biases (see the catalog and leakage audit).

## Datasets proposed for approval

| Dataset | Use | Why | Pre-condition |
|---|---|---|---|
| `imc25_smishing` | train / val / test | Largest real, recent, licensed scam-message set with type and lure labels | none (on disk, SHA-256 pinned) |
| `sp24_gateway_phishing` | test (cross-source, temporal); campaign detector train/test | Real timestamps and campaigns; little overlap with IMC'25 | none |
| `india_spam_sms_junioralive` | Indian legitimate + promotional negatives (train / val / test) | The only clearly licensed Indian legitimate SMS found; promotions are the hard negatives that drive alert fatigue | none (on disk, SHA-256 pinned); **approve despite undocumented provenance** |
| `uci_sms_spam` (official) | more legitimate negatives (train / val / test) | Clearly licensed, larger | **You download the official zip and register it** |
| `moz_smishing` | out-of-domain test (scam and legitimate) | Real mobile-money smishing with real legitimate messages | You download it and **confirm the dataset licence** |
| `ftc_csn_2024` | taxonomy and context tables only | Category and channel trends | You download it (optional) |

## Experiments

### E0 — Source-shortcut probe (CPU, minutes), runs first

Train TF-IDF + logistic regression to predict the **source dataset** from `text_masked` (IMC'25 vs UCI ham vs SP'24).
- If accuracy is far above chance, any scam-vs-legit score on mixed sources partly measures "which corpus is this". In that case only source-held-out results are reported for detection.
- Report: accuracy, plus the top features (to see which artefacts drive it).

### E1 — Message tagger: scam type (IMC'25 only; trainable today, CPU)

- **Task:** 8-class `scam_type` (banking, delivery, government, telecom, wrong number, hey mum/dad, others, spam).
- **Splits:** `imc25_group_v1`; unseen-family tests on `imc25_holdout_delivery_v1` and `imc25_holdout_government_v1`, each with a separately trained model. For an unseen family the question is whether it is still flagged as *some* scam with high confidence, or as "others".
- **Models:**
  1. Keyword / rules (brand and lure lexicons).
  2. TF-IDF (word 1–2-grams) + logistic regression.
  3. TF-IDF + linear SVM.
  4. Small transformer: multilingual MiniLM / DistilBERT fine-tune (GPU recommended).
  5. Current Chakravyuh tagger architecture (character n-gram TF-IDF, one-vs-rest LR), retrained on real data.
  6. Sentinel (Colab).
- **Metrics:** macro-F1, per-class P/R/F1, confusion matrix, accuracy, calibration (ECE of the max-class probability), latency per message.
- **Label caveat:** the labels are GPT-4o outputs, κ 0.93 against humans on 150 English messages. Scores above that agreement level aren't meaningful.

### E2 — Message tagger: lures / tactics (IMC'25; trainable today, CPU)

- **Task:** multi-label over 7 lures. Five map to our tactics: authority, urgency, greed, social_proof, reciprocity.
- **Metrics:** micro/macro-F1, per-label F1.
- **Caveat:** the labels are GPT-4o with κ 0.70 against humans, so this is agreement with a weak labeller, not accuracy. 8 of our 13 tactics have no real labels and are **not** evaluated on real data.

### E3 — Scam vs legitimate vs promotional (partly trainable today; stronger with the official UCI file)

- **Train:** IMC'25 scam (`imc25_group_v1` train) + Indian legitimate and promotional SMS (`india_spam_sms_junioralive_group_v1` train) + UCI ham once registered (`uci_group_v1` train).
- **Imbalance:** only ~1,100 legitimate and ~1,700 promotional training messages against ~23,000 scams. Use class weights; report per-class results.
- **Operating point:** the FPR target applies to legitimate *and* promotional messages separately. Flagging a Jio offer as a scam is the alert-fatigue failure we care about.
- **Tests:**
  - (a) in-distribution: the IMC'25 group test + the Indian negatives test (307 legitimate, 137 promotional after purging) + the UCI ham test when available.
  - (b) **cross-source:** SP'24 `test_novel_campaign` and `test_seen_campaign` (recall only).
  - (c) **out-of-domain:** MOZ (scam and legitimate, if licensed).
  - (d) **Indian subset:** IMC'25 test records with country IND (recall only).
- **Same models as E1 (1–6). Metrics:**
  - Precision, recall, F1, PR-AUC, ROC-AUC, FPR, FNR and confusion matrix, where both classes exist.
  - Recall/FNR only on single-class tests. Precision and FPR are reported as null, not estimated.
  - Calibration (ECE, reliability curve), and latency p50/p95.
  - Operating point: the threshold for FPR = 1% on the legitimate validation messages, then held fixed on every test. Promotional FPR is reported at that threshold.
- **Interpretation guard:** if E0 shows a strong source shortcut, (a) is reported but not used for claims.

### E4 — Campaign detector: novel campaigns over time (SP'24; trainable today, CPU)

- **Split:** `sp24_temporal_v1`.
- **Fit on train:** embeddings (TF-IDF or MiniLM) plus HDBSCAN, as in the current campaign detector.
- **Test:**
  - Are novel-campaign messages flagged as "unknown / new campaign" while seen-campaign messages map to existing clusters?
  - Cluster quality against the authors' campaign IDs where matched (ARI / NMI).
- **Metrics:** novelty AUROC (seen vs novel), ARI/NMI, time to first alert for a new campaign (how many messages before it forms a cluster).

### E5 — Sentinel (GPU; Colab)

- **Run:** `sentinel/colab_sentinel_real.ipynb` with config `sentinel/configs/sentinel_real_v1.json`. Base model Qwen2.5-1.5B-Instruct, 4-bit QLoRA (rank 16, alpha 32), 1 epoch, LR 2e-4, max 20k training examples, sequence length 512, loss on the JSON answer only.
- **Evaluation:** E1–E3 metrics via `sentinel/evaluate_real.py`, plus JSON validity and latency.
- **Record:** `sentinel/write_model_manifest.py` stores data, config and adapter hashes.
- **Unseen family:** a separate run with `sentinel_real_holdout_delivery_v1.json`.
- **Baseline comparison:** the same test files and the same operating-point rule as the E3 baselines.

## What cannot be trained on real data now

| Component | Status | Reason |
|---|---|---|
| ScamSeq | **Real-data sequence training currently unsupported by available public data.** | No public victim-side sessions. SP'24 timestamps are gateway arrivals across unrelated recipients, not one person's session. The scam-baiting e-mails are multi-turn but are not SMS/UPI, have no licence and would need annotation. ScamSeq stays on the synthetic track. |
| Payee graph | Unsupported | No real UPI/bank payee relationships are public. Elliptic++ (Bitcoin) can only test the graph *method*. PaySim stays a SYNTHETIC benchmark. |
| Fusion / alert policy | Message-level calibration only | Session-level outcomes don't exist publicly. |
| Hindi / Hinglish detection | Not claimable | Real data has 175 Hindi rows and under 30 Hinglish candidates. Synthetic Hinglish is for adversarial testing only, labelled SYNTHETIC. |

## Compute

| Experiment | Where | Rough cost |
|---|---|---|
| E0, E1/E2/E3 baselines 1–3 and 5, E4 | this environment (CPU) | minutes each |
| Simulator recalibration from PhonePe Pulse (synthetic track) | CPU | minutes |
| E1/E3 small transformer | Colab T4 or CPU (slow) | ~20–40 min on a T4 |
| E5 Sentinel | Colab T4 / your GPU | ~30–60 min training + inference over ~30k test messages |

## Reporting rules

1. Name every number with its track, split id, test file and operating threshold.
2. Report positive-only tests as recall/FNR only.
3. Report in-distribution and cross-source results side by side, with the larger gap stated.
4. No "real-world validated" wording. At most: "evaluated on held-out public real-world message datasets (IMC'25, SP'24, UCI, MOZ)".
5. Record the data SHA-256s and split ids for each model in its manifest.
