# Sentinel training results

**Status: AWAITING GPU RUN.** Training is approved (2026-10-04) for the v3 build: 8,000-scam stratified cap, clean text. No Sentinel model has been trained yet, so **this file contains no Sentinel numbers**. The build environment has no GPU and no Hugging Face access. The smoke test and the full run therefore happen in `sentinel/colab_sentinel_real_v3_scam8k.ipynb` on a Colab T4.

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

*Pending the Colab run.*

## Claims not made

Real-world deployment validation, UPI detection, session-level detection, payment prediction, Hindi/Hinglish capability, victim behaviour prediction.
