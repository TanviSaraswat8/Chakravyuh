# Sentinel training results

**Status: TRAINED AND EVALUATED (2026-10-04). Verdict: Sentinel did NOT pass the pre-registered criteria (failed 3 and 4).** It is not reported as an improvement, and the frozen character model remains the reference. Results are in section 6; the run record is in section 7. The run used `sentinel/colab_sentinel_real_v3_scam8k.ipynb` on a Colab T4.

Track: REAL PUBLIC DATA. The plan and the pre-registered criteria are in `SENTINEL_TRAINING_PLAN.md` (sections 9 and 11).

## 1. What will be trained

| Item | Value |
|---|---|
| Run name | `sentinel_real_v3_scam8k` |
| Config | `sentinel/configs/sentinel_real_v3_scam8k.json` (SHA-256 `806a46bd5e3f…`) |
| Base model | `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit` (Qwen2.5-1.5B-Instruct, 4-bit). The exact Hugging Face revision is recorded at run time in `training_log.json` |
| LoRA | rank 16, alpha 32, dropout 0; q/k/v/o/gate/up/down projections |
| Training | 1 epoch, LR 2e-4 cosine, 3% warm-up, batch 8 × grad-accum 2 = effective 16, max seq 384, seed 13 (also data seed), fp16 on T4 |
| Loss | assistant JSON only |
| Steps | ≈ 597 (9,551 / 16) |

## 2. Training corpus (frozen: `sentinel/manifests/sentinel_real_v3_scam8k.build.json`)

| File | Rows | Labels | SHA-256 (prefix) | vs v2 |
|---|---|---|---|---|
| train.jsonl | 9,551 | 8,000 scam / 1,044 legit / 507 promo | 621361d8c577 | new |
| val.jsonl | 3,435 | 3,208 scam / 133 legit / 94 promo | 4a016f1fe3d0 | **byte-identical** |
| every test file (IMC'25, India, S&P'24 seen/novel, UCI calibration/evaluation/spam) | as v2 | as v2 | as v2 | **byte-identical** |

- **Unchanged pieces.** Inputs, near-duplicate purge counts (computed before the cap) and the placeholder count (0) are identical to v2.
- **Baseline still valid.** The frozen baseline re-scored on the v3 files gives identical per-message scores (only timing differs) and identical metrics.
- **Held out.** UCI (both halves and spam) and S&P'24 are held out by `never_train`. The builder exits if either reaches train or val.

### Stratified scam sample (8,000 of 22,466 IMC'25 training scams)

- **Strata:** scam_type × language bucket (English / other), 14 strata.
- **Allocation:** proportional, with a floor of min(size, 150). The floor raises the small types: hey mum/dad from 0.8% to 2.3% and wrong number from 1.0% to 2.2%.
- **Within a stratum:** round-robin over near-duplicate clusters (one message per cluster before a second from any cluster). Inside each round, the rarest lure combination so far is taken first. Deterministic, seed 13.
- **Groups:** 7,793 of 11,555 near-duplicate clusters are represented, and 59 of 64 lure combinations.
- **Scam-type shares (pool → sample):**

  | Scam type | Pool | Sample |
  |---|---|---|
  | banking | 48.5% | 45.9% |
  | others | 21.2% | 21.2% |
  | delivery | 11.7% | 11.7% |
  | government | 10.0% | 10.0% |
  | telecom | 6.7% | 6.8% |
  | wrong number | 1.0% | 2.2% |
  | hey mum/dad | 0.8% | 2.3% |

- **Lure shares (pool → sample):** authority 80.2% → 75.6%; urgency 79.6% → 71.7%; distraction 32.9% → 35.7%; need/greed 16.8% → 18.8%; kindness 1.9% → 3.8%. Rare lures are mildly up-weighted.
- **Source / group information:** IMC'25 is the only scam source in training. Its group information is the near-duplicate cluster, which the sampling spreads across. Country is missing for most IMC'25 rows, so it is not a stratum.
- **Exact sampled IDs:** `sentinel/manifests/sentinel_real_v3_scam8k.sampled_scam_ids.json` (IDs only, no text; SHA-256 `5174f87a8089…`). `verify_build.py` checks the rebuilt list against it byte-for-byte.

## 3. Run procedure (Colab notebook)

1. Fetch the pinned datasets and upload the UCI zip; the notebook asserts SHA-256 `1587ea43…963ce3`.
2. Rebuild, then run `verify_build.py`. The run stops unless it prints **BUILD MATCHES APPROVED MANIFEST**.
3. **Smoke test:** train on 50 messages for 5 steps, then score 50 messages per test file. `smoke_check.py` gates on:
   - finite loss;
   - the loss-mask check (every example keeps supervised answer tokens);
   - the adapter saved;
   - prediction ids matching;
   - valid label probabilities;
   - JSON generation running;
   - a latency file written.

   **If it fails, the notebook stops and the failure is reported. The experiment is not changed silently.**
4. Full run with the approved hyperparameters. `training_log.json` records:
   - start and end time and duration;
   - GPU, CUDA and package versions;
   - the base-model revision;
   - the LoRA config and the full loss history.

   `hardware.txt` holds the `nvidia-smi` output.
5. `predict_hf.py`: p_scam on every test file, JSON generation on the IMC'25 test, and batch-1 latency.
6. `evaluate_cross_source.py`: threshold by the pre-registered UCI-calibration rule, per-source metrics and source pairs.
7. `check_acceptance.py`: the five criteria, applied mechanically against the frozen baseline.
8. `write_model_manifest.py`: data and config hashes and the adapter checksum.
9. Two downloads:
   - `sentinel_real_v3_scam8k_results.zip`: metrics, predictions, logs and manifests, no weights. Send this one back.
   - `sentinel_real_v3_scam8k_adapter.zip`: the weights. Not committed.

## 4. Frozen baseline on the same files (CPU, committed)

**Model:** `e3__clean__chakravyuh_tagger_arch`, artifact SHA-256 `56cc0133…`, unchanged.
**Metrics:** `sentinel/baselines/sentinel_real_v3_scam8k/chakravyuh_tagger_arch/metrics.json`.
**Threshold:** 0.9681 [95% CI 0.9567, 0.9744], chosen on the UCI ham calibration half (n = 2,393).

| Source | Metric at calibrated threshold | Baseline [95% CI] |
|---|---|---|
| IMC'25 test (n 5,767) | recall | 0.723 [0.711, 0.734] |
| India test (303 legit / 142 promo) | legit FPR / promo FPR | 0.000 / 0.014 [0.000, 0.035] |
| UCI ham evaluation (n 2,400) | legit FPR | 0.013 [0.009, 0.018] |
| UCI spam (n 747) | flag rate (not recall) | 0.125 |
| S&P'24 seen / novel | recall | 0.990 / 0.936 |

**Source pairs.** These are one scam source against one legitimate source, never merged. Pair precision depends on that pair's prevalence and is not a deployment precision.

| Pair | Precision | PR-AUC | ROC-AUC | ECE |
|---|---|---|---|---|
| IMC'25 vs UCI ham evaluation | 0.992 | 0.986 | 0.963 | 0.075 |
| IMC'25 vs India legit | 1.000 | 0.999 | 0.988 | 0.049 |
| IMC'25 vs India promo | 0.9995 | 0.9995 | 0.984 | 0.055 |
| S&P'24 novel vs UCI ham evaluation | 0.997 | 0.994 | 0.989 | 0.069 |
| S&P'24 seen vs UCI ham evaluation | 0.990 | 0.991 | 0.995 | 0.161 |
| S&P'24 novel vs India promo | 0.9998 | 0.9994 | 0.987 | 0.025 |

Confusion counts per source and per pair, argmax results and the full threshold curve are in the metrics JSON. Baseline latency is the CPU per-message time within a batch, so it is not comparable to GPU latency.

## 5. Pre-registered acceptance criteria (unchanged; applied by `sentinel/check_acceptance.py`)

1. UCI ham evaluation FPR ≤ 1.5%, and its 95% CI upper bound ≤ 2.5%.
2. India promotional FPR ≤ 5%.
3. IMC'25 recall ≥ 0.723 + 0.03, with non-overlapping bootstrap CIs (Sentinel's lower bound above the baseline's upper bound of 0.734).
4. S&P'24 novel-campaign recall ≥ 0.90.
5. JSON validity ≥ 99% on generated IMC'25 outputs.

**Reporting:**
- **If all pass**, the wording is exactly: "Sentinel v2 passed the pre-registered evaluation criteria on held-out public real-world message datasets." (The plan calls it Sentinel v2; the trained run is the v3 build.)
- **Otherwise** it is reported as not better, and the character model stays the reference. No retuning until it wins.
- **Recall up but false alarms up substantially:** not an improvement. The checker lists every false-alarm rate that is above the baseline's.
- **Higher overall F1 is not a criterion.**

## 6. Results

Run `sentinel_real_v3_scam8k`, at code commit `753fd667fe710a091572ef445598530a97a5a1e6`. Committed records are in `sentinel/results/sentinel_real_v3_scam8k/`:
- `metrics_real.json`, `acceptance.json`;
- `training_log.json`, `MODEL_MANIFEST.json`;
- `scoring_config.json`, `latency_single.json`;
- the smoke-test records, `hardware.txt`, `ARTIFACTS.json`.

Weights and per-message predictions are not committed.

### Pre-registered acceptance (`sentinel/check_acceptance.py`)

| # | Criterion | Sentinel [95% CI] | Baseline [95% CI] | Result |
|---|---|---|---|---|
| 1 | UCI ham evaluation FPR ≤ 1.5%, CI upper ≤ 2.5% | 0.0058 [0.0029, 0.0092] | 0.0133 [0.0092, 0.0183] | pass |
| 2 | India promotional FPR ≤ 5% | 0.000 | 0.014 [0.000, 0.035] | pass |
| 3 | IMC'25 recall ≥ 0.7531, non-overlapping CIs | **0.6655 [0.654, 0.678]** | 0.7231 [0.711, 0.734] | **fail** |
| 4 | S&P'24 novel-campaign recall ≥ 0.90 | **0.0311 [0.028, 0.035]** | 0.9358 [0.931, 0.941] | **fail** |
| 5 | JSON validity ≥ 99% (IMC'25 generated) | 1.000 | n/a | pass |

**Verdict:** Sentinel did NOT pass the pre-registered criteria (failed 3 and 4). It is not reported as an improvement. The frozen character model (`e3__clean__chakravyuh_tagger_arch`) remains the reference. **No retuning was done.**

### Per source, at the calibrated threshold (never merged)

**Thresholds** (UCI ham calibration half, n = 2,393, same rule for both):

| Model | Threshold | 95% CI |
|---|---|---|
| Sentinel | 0.99778 | [0.99723, 0.99804] |
| Baseline | 0.96807 | [0.95668, 0.97443] |

| Source | Metric | Sentinel | Baseline |
|---|---|---|---|
| IMC'25 test (5,767) | recall | 0.666 | 0.723 |
| IMC'25 Indian-network subset | recall | 0.794 | 0.855 |
| India test (303 legit / 142 promo) | legit FPR / promo FPR | 0.000 / 0.000 | 0.000 / 0.014 |
| UCI ham evaluation (2,400) | legit FPR | 0.006 | 0.013 |
| UCI spam (747) | flag rate (not recall) | 0.062 | 0.125 |
| S&P'24 seen (3,072) | recall | **0.010** | 0.990 |
| S&P'24 novel (10,510) | recall | **0.031** | 0.936 |

**At argmax** (reported, not used for the decision): Sentinel flags 48.7% of UCI ham evaluation messages as scam (baseline 35.6%), and 23.9% of India promotions (baseline 12.0%). Its recall is 0.985 on IMC'25 and 0.999 on S&P'24 novel.

### Source pairs (same threshold; pair precision depends on the pair's prevalence)

| Pair | Precision | PR-AUC | ROC-AUC | ECE (Sentinel / baseline) |
|---|---|---|---|---|
| IMC'25 vs UCI ham evaluation | 0.996 | 0.983 (baseline 0.986) | 0.958 (0.963) | 0.128 / 0.075 |
| IMC'25 vs India legit | 1.000 | 0.9995 (0.9993) | 0.991 (0.988) | 0.017 / 0.049 |
| IMC'25 vs India promo | 1.000 | 0.9997 (0.9995) | 0.987 (0.984) | 0.017 / 0.055 |
| S&P'24 novel vs UCI ham evaluation | 0.959 | 0.962 (0.994) | 0.934 (0.989) | 0.082 / 0.069 |
| S&P'24 seen vs UCI ham evaluation | 0.682 | 0.886 (0.991) | 0.943 (0.995) | 0.210 / 0.161 |
| S&P'24 novel vs India promo | 1.000 | 0.9998 (0.9994) | 0.993 (0.987) | 0.011 / 0.025 |

### Other measurements

- **IMC'25 scam_type macro-F1:** 0.698, measured against GPT-4o weak labels.
- **Latency, Tesla T4:** one p_scam forward pass at batch 1 takes p50 116 ms, p95 161 ms. Batched, it's about 16–23 ms per message. The baseline is CPU, so its latency isn't comparable.

### Why it failed (diagnosis only; nothing was changed in response)

**The scores saturate.** Sentinel's p_scam is crowded near 1:
- **UCI legitimate messages:** about 6–7% score ≥ 0.99, and the 99th percentile is 0.9977.
- **S&P'24 scams:** almost all score 0.98–0.999 (median 0.990).
- **The consequence:** to keep UCI false alarms at 1%, the pre-registered rule must set the threshold at 0.9978, and that is above almost every S&P'24 score.

**Ranking is weaker too, not just shifted.** S&P'24 vs UCI ham ROC-AUC is 0.93–0.94, against 0.99–0.995 for the baseline. So no threshold would give Sentinel the baseline's trade-off on these sources.

**On IMC'25, the source it was trained on, ranking is comparable** (PR-AUC 0.983 vs 0.986). It still loses recall at the strict threshold.

**Where it does better:** fewer false alarms on legitimate and promotional SMS at the calibrated threshold, and better calibration (ECE) on the India pairs. That doesn't make it an improvement under the pre-registered criteria, which also require scam recall.

**Interpretation, stated as a hypothesis and not tested:** the 1.5B LLM, trained on IMC'25 scams plus a small Indian legit/promo set, learned source style. It doesn't separate independent legitimate SMS (UCI) from scams of another source (S&P'24) as well as the character n-gram model. This matches the E6 source-separability finding.

## 7. Run record

| Item | Value |
|---|---|
| Code commit | `753fd667fe710a091572ef445598530a97a5a1e6` (v3 build `ab5c07b` + scoring-length fix) |
| Build | `BUILD MATCHES APPROVED MANIFEST` on the runtime. 8,000 unique sampled scam IDs, byte-identical to the frozen list. All row and label counts match; 0 placeholders |
| UCI zip | SHA-256 `1587ea43e58e82b14ff1f5425c88e17f8496bfcdb67a583dbff9eefaf9963ce3`, checked by the notebook and again on the runtime |
| Base model | `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit`, revision `d2f2dd02b071701d5100a04a7a49d6fb0bd305b7` |
| LoRA / training | rank 16, alpha 32, dropout 0, 7 projections. 1 epoch, LR 2e-4 cosine, 3% warm-up, batch 8 × 2 = 16, max seq 384, seed 13, fp16 |
| Hardware / software | Tesla T4 (15 GB), CUDA 13.0, Python 3.13. torch 2.11.0, transformers 5.5.0, trl 0.24.0, peft 0.21.0, unsloth 2026.9.14, bitsandbytes 0.50.2 |
| Smoke test | passed (5 steps, loss 0.513 → 0.189; smoke JSON validity 0.96, reported only) |
| Training | completed: 597 steps, 2,096 s (11:54–12:30 UTC). Training loss 0.218 → 0.060; validation loss 0.0718 → 0.0598 → 0.0563 (steps 200 / 400 / end) |
| Training truncation | 14 of 9,551 training examples exceed 384 tokens and were truncated by the approved 384-token training length (`train_tokens_over_max_seq`) |
| Adapter | `adapter_model.safetensors` SHA-256 `fe0dfc0c3bfcdd3ef9c4fbf73229fb0f54fc5acfd849a6768f45c6fe6be7ff4a`. Zipped and secured on the owner's laptop **before scoring started** |
| Scoring | effective max sequence 682 tokens (longest prompt 586 + 96 generation; model context 32,768). **0 truncated.** 25,334 / 25,334 test messages scored. 6 IMC'25 prompts exceed 384 tokens and were scored in full |
| Artifacts | adapter zip SHA-256 `27813643179cf8483e082276b7fdd3f7b00e1160bfca965ab7e8d37c64634ca4` (70,604,245 B). Results zip SHA-256 `45d0425ec7d2fee8e00a655ba36d601faaacbe257dd17214eaf6fab53ef04db7` (896,018 B). Both verified on the laptop; not committed |

**Incidents, recorded for completeness:**
1. **First run (same config, commit `ab5c07b`):** training completed, but scoring failed. The model was loaded with a 384-token context while prompts are deliberately not truncated, so a 457-token batch overran it. The Colab runtime then expired while idle, and that adapter was lost **before any prediction or metric existed**. The approved fix `753fd667` changes scoring only.
2. **Second run:** the browser lost its connection to the runtime for about 15 minutes during scoring. The runtime and the scoring process continued; the same VM was reattached and all outputs verified.

## Claims not made

Real-world deployment validation, UPI detection, session-level detection, payment prediction, Hindi/Hinglish capability, victim behaviour prediction.
