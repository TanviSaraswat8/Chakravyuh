# Sentinel v2 (clean text): training plan

**Status: APPROVED 2026-10-04 for the v3 build (8,000-scam stratified cap; section 11). Not yet trained; results go to `SENTINEL_TRAINING_RESULTS.md`.** Sections 1–10 describe the v2 design and stay as written, since they are the pre-registration. Section 11 lists the only differences.

- **Track:** REAL PUBLIC DATA.
- **Synthetic data:** none. The shipped simulator-trained tagger (`backend/artifacts/tagger.pkl`) stays separate. It appears only as a labelled zero-shot reference in E2/E3/E5 and is untouched by this plan.

## Why this design

E5–E7 (`REAL_CROSS_SOURCE_VALIDATION.md`) found three problems this design is built around:
1. The masked text carried a source artefact. **Sentinel therefore uses clean text only**, and the builder refuses to write a build if any placeholder token remains: the frozen build has 0.
2. Probabilities don't transfer across sources. **The operating threshold is therefore calibrated on independent legitimate SMS (a UCI ham calibration half), never on the 133-message India validation set.**
3. Two legitimate corpora are not "normal SMS". **Every result is therefore reported per source, with UCI and S&P'24 kept external.**

Design S0 keeps the *same training data as E3*, so Sentinel and the E3 character model are compared on identical messages. That answers the one open question: does a small LLM learn more transferable scam behaviour than character n-grams?

## 1. Training corpus (clean text)

| Source | Use | Labels | Rows |
|---|---|---|---|
| IMC'25 (`imc25_group_v1` train/val) | train, val | `scam` with scam_type + lures (GPT-4o weak labels). IMC'25 "spam" excluded as ambiguous, as in E3 | train 18,449 (capped) / val 3,208 |
| India SMS (`india_spam_sms_junioralive_group_v1` train/val) | train, val | `legit`, `promo` (its "spam") | train 1,044 legit + 507 promo / val 133 + 94 |
| S&P'24 (`sp24_temporal_v1` test) | **external test only** | `scam` | 3,072 seen + 10,510 novel |
| UCI official (`uci_ham_calibration_v1`) | **calibration + external test only** | ham → `legit`; spam → `uci_spam` (flag rate only) | calibration 2,393 / evaluation 2,400 / spam 747 |

- **Text:** the `clean` variant. ftfy 6.3.1 repairs mis-decoded text, then the shared masking is applied and every placeholder is removed. The 35 chat-export placeholder rows are excluded.
- **Training cap:** 20,000 examples. All 1,551 legitimate and promotional examples are kept and scams are subsampled (seed 13). **The training set is about 92% scam.** That is a known risk, handled by calibrated thresholds; see Risks.
- **Excluded from training:** `never_train` = UCI and S&P'24. The builder fails if either reaches train or val.

## 2. Manifests, provenance and hashes

- **Approved build manifest (committed):** `sentinel/manifests/sentinel_real_v2_clean.build.json`. It records:
  - the config SHA-256;
  - SHA-256 of every input (processed datasets and split files);
  - SHA-256 and row counts of every output file;
  - purge counts and the placeholder count (0).
- **Raw dataset provenance:** `data/registry/*.json` (versions, licences, raw SHA-256). UCI: zip `1587ea43…963ce3`.
- **`sentinel/verify_build.py`** must print `BUILD MATCHES APPROVED MANIFEST` before training. The Colab notebook runs it, and the build was confirmed byte-reproducible by a clean rebuild.

| File | Rows | SHA-256 (prefix) |
|---|---|---|
| train.jsonl | 20,000 | 7ecd1da83077 |
| val.jsonl | 3,435 | 4a016f1fe3d0 |
| test_imc25_group_v1_test | 5,767 | 07744274a026 |
| test_india_…_test | 445 | f0e148d7184c |
| test_sp24 seen / novel | 3,072 / 10,510 | f4a77e92ea1c / 019c62f39bd2 |
| test_uci calibration / evaluation / spam | 2,393 / 2,400 / 747 | 652defaf85e5 / 76f931d000b4 / 746a2bc6b978 |

## 3. Leakage-safe split

- **Grouped and temporal splits:** IMC'25 and India use near-duplicate-grouped splits; S&P'24 uses its temporal split.
- **Purge before writing:** any test example that is a near-duplicate of any train or val example, computed on the exact prompt text, is dropped. That removed 637 IMC'25, 9 India, 26 S&P'24 and 10 UCI examples.
- **Calibration vs evaluation:** the UCI calibration and evaluation halves are split by near-duplicate group, identical to E7, so thresholds are never chosen on the evaluation half.

## 4. Model configuration

| Item | Value |
|---|---|
| Base model | `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit` (Qwen2.5-1.5B-Instruct; check the licence on the model card at download) |
| Adapter | LoRA rank 16, alpha 32, dropout 0, on q/k/v/o/gate/up/down projections; base frozen in 4-bit (QLoRA) |
| Output | JSON: `{"label": scam\|promo\|legit, "scam_type": …\|null, "lures": [...]}`. The system prompt treats the message as data |
| Score for thresholds | `p_scam`: probability of the first label token for "scam", renormalised over scam/promo/legit, after the forced prefix `{"label": "` (one batched forward pass) |
| On-device option (later) | GGUF Q4_K_M export (`--export-gguf`), or the same recipe on Qwen2.5-0.5B |

## 5. Training configuration

| Item | Value |
|---|---|
| Epochs | 1 |
| LR / schedule | 2e-4, cosine, 3% warm-up |
| Batch | 8 per device × gradient accumulation 2 (effective 16) |
| Max sequence | 384 tokens |
| Loss | assistant JSON only (`train_on_responses_only`) |
| Precision | fp16 on T4 |
| Seed | 13 |
| Validation | every 200 steps on `val.jsonl` |

Exact command:

```bash
python sentinel/finetune.py --base unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit --data sentinel/sft_real/sentinel_real_v2_clean \
  --out sentinel/outputs/sentinel_real_v2_clean --max-seq 384 --epochs 1 --lr 2e-4 --rank 16 --batch 8 --grad-accum 2 --seed 13
```

## 6. Evaluation protocol (`sentinel/evaluate_cross_source.py`)

Applied identically to Sentinel and to the frozen baseline.

- **Per source, never merged:**
  - IMC'25 test: recall, the Indian-network subset recall, scam_type macro-F1 and JSON validity on generated outputs;
  - India test: legitimate and promotional FPR;
  - UCI evaluation half: legitimate FPR;
  - UCI spam: flag rate only;
  - S&P'24: seen and novel campaign recall.
- **Decisions:** the argmax label, and the calibrated threshold (section 7).
- **Curves:** thresholds 0.05–0.999, every source, Wilson 95% CIs.
- **Bootstrap CIs** on recall and FPR; latency per message.
- **Labels:** every output is stamped `track: REAL PUBLIC DATA`.

## 7. Threshold-selection procedure (exact)

1. Score the UCI ham **calibration** half (n = 2,393) with `p_scam`.
2. Sort the scores in descending order, let k = floor(0.01 × n) = 23, and set the threshold just above the (k+1)-th highest score (`nextafter`). At most 1% of calibration messages are flagged, and ties are handled.
3. Bootstrap the calibration set 500× (seed 13) and repeat step 2 for the threshold's 95% CI. Report flag rates at both ends of the CI.
4. Apply the threshold unchanged to every source. The UCI **evaluation** half gives the independent legitimate FPR.
5. Report the full curve as well. **No single threshold is presented as universal.** E7 showed steep recall cliffs between 0.97 and 0.98.

## 8. The baseline to beat (same files, same rule; measured on CPU, committed)

**Model:** frozen E3 `chakravyuh_tagger_arch`, clean text. Source: `sentinel/baselines/sentinel_real_v2_clean/chakravyuh_tagger_arch/metrics.json`.

| Item | Value |
|---|---|
| Threshold [95% CI] | 0.968 [0.957, 0.974] |
| IMC'25 recall | 0.723 |
| India legit FPR / promo FPR | 0.000 / 0.014 |
| UCI ham evaluation FPR | 0.013 |
| UCI spam flag rate | 0.125 |
| S&P'24 recall, seen / novel | 0.990 / 0.936 |

## 9. Pre-registered acceptance criteria

These are decided before training, at the calibrated threshold. **Sentinel is "better" only if all of these hold:**

1. UCI ham evaluation FPR ≤ 1.5%, and its 95% CI upper bound ≤ 2.5%.
2. India promotional FPR ≤ 5%.
3. IMC'25 recall exceeds the baseline's 0.723 by at least 0.03, with non-overlapping bootstrap CIs.
4. S&P'24 novel-campaign recall ≥ 0.90.
5. JSON validity ≥ 99% on generated outputs.

Otherwise the result is reported as **not better**, and the character model remains the reference. Either way:
- no real-world deployment claim;
- no Hindi/Hinglish claim (real Hindi test data is 175 rows);
- no session, UPI or payee claim.

## 10. GPU / Colab requirements

| Item | Requirement |
|---|---|
| GPU | NVIDIA T4 16 GB (Colab free / Pro) or better (L4, A100) |
| Runtime | ≈ 45–75 min on a T4: training ≈ 35–50 min for 1,250 steps; batched scoring of ~25k test messages ≈ 10 min; JSON generation on the IMC'25 test ≈ 10–15 min. Colab free sessions can disconnect; checkpoints save every 400 steps |
| Disk / RAM | ~10 GB disk, 12 GB system RAM |
| Network | GitHub (repo + pinned datasets), PyPI, Hugging Face (base model download) |
| Upload | the UCI zip (the notebook checks SHA-256 `1587ea43…963ce3`) |
| Notebook | `sentinel/colab_sentinel_real_v2_clean.ipynb` |

## Risks

- **Imbalance:** about 92% scams in training. The model may call almost everything a scam at argmax. Calibration is the mitigation; a run with the scam class capped at 8,000 is a fallback if the argmax false-alarm rate is extreme.
- **Weak labels:** scam_type and lures are GPT-4o labels, scored as agreement with GPT-4o.
- **Narrow legitimate data:** E6 shows the sources remain about 90% separable, so any model can still learn source style.
- **Untested GPU scripts:** `predict_hf.py` and the training path were written without GPU access or model downloads here. The notebook runs a 50-message smoke test first, which prints the label-token ids.

## 11. Approved run: v3 (8,000-scam stratified cap) — addendum, 2026-10-04

Approved instead of the 20,000-example v2 cap. **The objective is robust scam / legitimate / promotional discrimination across unseen sources, not the dominant class.** Everything in sections 1–10 is unchanged, including:
- the model and hyperparameters;
- the threshold rule;
- the five acceptance criteria;
- held-out UCI and S&P'24;
- the baseline.

The differences:

| Item | v2 (sections 1–10) | v3 (approved) |
|---|---|---|
| Config | `sentinel_real_v2_clean.json` | `sentinel_real_v3_scam8k.json` |
| Training scams | 18,449, simple random cap | **8,000, stratified** (scam_type × language, floor 150; round-robin over near-duplicate clusters; rarest lure combination first; seed 13) |
| Training legit / promo | 1,044 / 507 | 1,044 / 507 (all kept) |
| Train rows / share scam | 20,000 / 92% | 9,551 / 84% |
| Validation and every test file | — | **byte-identical to v2** (checked by SHA-256) |
| Frozen manifest | `sentinel_real_v2_clean.build.json` | `sentinel_real_v3_scam8k.build.json` + `sentinel_real_v3_scam8k.sampled_scam_ids.json` |
| Notebook | `colab_sentinel_real_v2_clean.ipynb` | `colab_sentinel_real_v3_scam8k.ipynb` |
| Steps (effective batch 16) | ≈ 1,250 | ≈ 597 |

**Smoke test (gate before full training):**
- `finetune.py --limit 50 --max-steps 5` (same hyperparameters), then `predict_hf.py --limit 50`, then `smoke_check.py`.
- It checks pipeline mechanics only. It fails on:
  - non-finite loss;
  - a broken loss mask;
  - a missing adapter;
  - mismatched prediction ids;
  - invalid label probabilities;
  - missing JSON generation;
  - missing latency output.
- On failure the notebook stops and the failure is reported. Nothing is changed silently.

**Added reporting (no change to decisions):**
- source-pair precision, PR-AUC, ROC-AUC, ECE and confusion counts at the same calibrated threshold;
- latency p50/p95 and batch-1 latency.

`sentinel/check_acceptance.py` applies section 9 mechanically. Its limits are constants in the file.

**Code fixes made before any Sentinel result exists (scoring is unchanged):**
- `predict_hf.py` no longer truncates prompts, which could have cut off the forced label prefix.
- It generates JSON in batches (sequential generation would have taken hours on a T4).
- It counts JSON as valid only if the whole output parses and contains a valid label.

