# Sentinel v4: proposal (not approved, not run)

**Status: PROPOSAL, awaiting approval.** Nothing here has been trained or scored.

- **Track:** REAL PUBLIC DATA.
- **Reference model:** the frozen E3 character model (`e3__clean__chakravyuh_tagger_arch`) stays the reference unless a run passes its pre-registered criteria.

## Why a v4 at all, and the first decision

Sentinel v3 did not pass (`SENTINEL_TRAINING_RESULTS.md`). The diagnosis was:
1. **The scores saturate.** About 6–7% of independent legitimate SMS (UCI) score p_scam ≥ 0.99. The 1%-false-alarm threshold therefore lands at 0.9978, above almost all S&P'24 scams (median 0.990).
2. **The ranking is weaker than the baseline across sources.** S&P'24 vs UCI ham ROC-AUC is 0.93–0.94, against the baseline's 0.99. A threshold change alone cannot fix that.

Hypothesis, untested: with 84% scams, almost all from IMC'25, and legitimate examples from a single Indian corpus, the model learned "IMC'25-like vs India-like" rather than "scam vs not". That is consistent with E6.

**Decision 0 (yours): continue Sentinel at all?**
- **Stopping is a legitimate outcome.** The character model already meets every UCI, India and S&P'24 criterion except the +0.03 IMC'25 margin. It is cheaper, and it runs on CPU.
- **Recommendation:** run v4 only if an LLM tagger matters for the project, for example its scam_type and lure JSON output. JSON validity was 100% and scam_type macro-F1 0.698.

## A caveat that applies to any v4: the test sets are no longer untouched

v4's design is informed by v3's results on the IMC'25, UCI and S&P'24 test files. Re-using them as the only acceptance tests risks fitting the design to those test sets. Mitigations, all pre-registered:
- **One run, one design.** It is fixed below before any v4 number exists, with no variants and no re-runs to "fix" a miss. A failed v4 is reported as failed.
- **A fresh external test that nobody has looked at:** MOZ mobile-money smishing (`moz_smishing`, real scam + legitimate). This needs you to download it and confirm its licence (catalog status: REQUIRES_LOCAL_DOWNLOAD, licence UNRESOLVED). If it can't be licensed, the v4 report must say that every acceptance test was previously used to design it.
- The UCI calibration/evaluation halves and the threshold rule stay exactly as before.

## Design (one change of substance, chosen from the diagnosis)

| Item | v3 | v4 proposal |
|---|---|---|
| Base model, LoRA, LR, epochs, seed, max seq | Qwen2.5-1.5B 4-bit, r16/α32, 2e-4, 1 epoch, seed 13, 384 | **unchanged** |
| Training scams | 8,000 stratified (84% of train) | **1,551 stratified**, using the v3 sampler, so scam : (legit + promo) = 1 : 1 |
| Training legit / promo | 1,044 / 507 (India) | unchanged |
| Validation, tests, labels, threshold rule, evaluation code | — | **unchanged** (plus MOZ as an extra external test, if licensed) |
| Scoring | full-length prompts, 0 truncation (fix `753fd667`) | unchanged |

**Why this single change:** it directly tests the hypothesis that the 84% scam prior and the volume of IMC'25 style cause the saturation. It is one variable, so a result is interpretable.

**What it does not address:** the legitimate data still comes from one Indian corpus. No additional clearly-licensed legitimate SMS source is available. UCI is reserved for calibration and evaluation, and moving it into training would remove the independent false-alarm test. This limit is stated up front.

**Cost:** about 3,100 training rows, about 195 steps, roughly 15 minutes of training on a T4 plus about 50 minutes of scoring. The same Colab notebook pattern is used, with the adapter secured before scoring.

## Pre-registered acceptance (decided now, before any v4 number exists)

The same five criteria as v3 (`SENTINEL_TRAINING_PLAN.md` section 9), applied mechanically by `sentinel/check_acceptance.py`, plus one:

6. **If MOZ is licensed:** on MOZ, at the same UCI-calibrated threshold, recall must be no lower than the baseline's, with legitimate false alarms ≤ 5%. Both models are scored on the same MOZ files, and the result is reported per source. Thresholds for MOZ are decided now; MOZ numbers are not looked at before the v4 run.

**Reporting rules (unchanged):**
- Every source is reported separately; there is no merged headline and no "win" on overall F1.
- If recall improves but false alarms rise substantially, the result is not called an improvement.
- If all criteria pass, the wording is exactly: "Sentinel v4 passed the pre-registered evaluation criteria on held-out public real-world message datasets."
- **No claims of:** real-world deployment validation, UPI detection, session-level detection, payment prediction, Hindi/Hinglish capability, or victim behaviour prediction.

## What needs your approval

1. Decision 0: continue Sentinel (v4) or stop and keep the character model.
2. If continuing: the single design change above, and these criteria.
3. MOZ: whether you'll download it and confirm its licence. Without it, v4 has no untouched test.

Nothing will be built, trained or scored until you approve.
