# Data leakage audit (real message data)

Measured on 2026-10-03 with `scripts/validate_real_dataset.py --all` and `scripts/leakage_audit.py`.
Raw JSON is in `data/reports/` (counts only, no message text; regenerate with the same scripts). Nothing was trained.

## Method

- **Normalisation (`chakravyuh/realdata/textnorm.py`).** Every source gets the same masking: URLs, e-mails, UPI IDs and digit runs become `<URL>/<EMAIL>/<VPA>/<NUM>`, and every source-specific mask token (`<NAMED_ENTITY>`, `#OTP` ...) becomes `<MASK>`.
- **Exact duplicate.** The same key after normalisation, lower-casing and punctuation removal.
- **Near duplicate.** MinHash over character 5-grams (64 permutations, LSH 8×8), joined when the estimated Jaccard is ≥ 0.8 (union-find).
- **Template.** The exact key with every placeholder collapsed to one token. Messages that differ only in links, numbers or names share a template.
- **Leakage of a split.** The share of test records whose near-duplicate cluster also appears in training.

## Findings

### 1. Random splits leak badly

| Dataset | Records | Unique after normalisation | Near-dup clusters | Largest cluster | Test records with a near-duplicate in train (random 80/20) |
|---|---|---|---|---|---|
| sp24_gateway_phishing | 68,029 | 12,767 | 2,464 | 9,273 | **98.4%** |
| imc25_smishing | 33,869 | 23,256 | 18,076 | 1,165 | **56.1%** |
| smishtank (mirror) | 1,062 | 951 | 847 | 29 | 26.8% |
| nus_sms_corpus | 55,835 | 47,101 | 46,830 | 377 | 21.1% |
| uci_sms_spam (mirror) | 5,574 | 5,095 | 4,982 | 30 | 16.3% |
| mishra_soni (mirror) | 5,971 | 5,699 | 5,486 | 16 | 11.1% |
| super_sms | 67,008 | 65,638 | 62,550 | 75 | 9.1% |
| india_spam_sms_junioralive | 2,267 | 1,920 | 1,845 | 35 | 29.7% |

A model evaluated on a random split of SP'24 is mostly re-reading training messages. **Every real-data
split in this project groups whole near-duplicate clusters on one side.**

### 2. The well-known SMS corpora are not independent

Near-duplicate share of the first dataset's records found in the second (≥1% shown):

| From → to | Near-dup | Exact (unique texts) |
|---|---|---|
| uci_sms_spam → mishra_soni_smishing | 97.5% | 96.6% |
| uci_sms_spam → super_sms | 89.9% | 84.2% |
| uci_sms_spam → nus_sms_corpus | 72.5% | 68.3% |
| mishra_soni → uci_sms_spam | 89.0% | 86.3% |
| mishra_soni → super_sms | 81.9% | 73.7% |
| nus_sms_corpus → super_sms | 69.4% | 72.0% |
| super_sms → nus_sms_corpus | 52.0% | 51.7% |
| smishtank → imc25_smishing | **49.3%** | 0.8% |
| imc25_smishing → super_sms | 4.5% | 0.1% |
| imc25_smishing → smishtank | 2.7% | 0.0% |
| sp24 → imc25_smishing | 2.5% | 0.0% |
| imc25_smishing → sp24 | 1.5% | 0.0% |
| india_spam_sms_junioralive → nus_sms_corpus | 6.3% | 2.2% |
| india_spam_sms_junioralive → uci_sms_spam | 2.7% | 0.3% |

Consequences:
- UCI, Mishra & Soni, Super SMS and NUS are one family. Training on one and testing on another is not an independent test. Only **one** of them (official UCI) is planned for use.
- SmishTank is largely inside IMC'25, because IMC'25 ingested SmishTank reports (the near-duplicate share is high while the exact share is low: same messages, transcribed differently). SmishTank is not an independent test of an IMC'25-trained model.
- IMC'25 and SP'24 overlap little (1.5–2.5%), so SP'24 is a reasonable **cross-source** test for an IMC'25-trained model, once the overlapping records are purged.

### 3. Source artefacts (shortcut risk)

82.4% of IMC'25 records contain a mask token. The figure is 1.6% for NUS, 0.75% for Super SMS and 0.02% for UCI.
If IMC'25 scams are mixed with UCI ham, a classifier can learn "has a mask token = scam".
Controls:
1. Shared masking applies to every source (`text_masked`).
2. A **source-prediction probe** runs before any detection result is trusted: a classifier is trained to predict the *dataset* from `text_masked`. If it is near-perfect, scam-vs-legit numbers on mixed sources are not credible. This is Experiment E0 in `REAL_TRAINING_PLAN.md`.
3. Detection is always reported on a **source-held-out** test as well (train on IMC'25 + UCI, test on SP'24 and MOZ).

### 4. Family and country overlap (IMC'25)

- **Families:** 427 near-duplicate clusters (12.3% of records) span more than one scam type. These are the same message labelled differently by GPT-4o, so there is label noise and leakage across families. Family-held-out splits purge these from training (217 records for "delivery", 476 for "government").
- **Countries:** 868 clusters (26.9% of records) span more than one sending-network country. A held-out-country test needs the same purge.

### 5. Time

- **SP'24 has real Unix timestamps** (2022-05-01 to 2023-06-01), but 73% of messages fall in April–May 2023.
- **Temporal split:** train before 2023-05-04, validation to 2023-05-11, test after. Only **22.7%** of test messages belong to a near-duplicate cluster seen in training (3,084 seen-campaign, 10,524 novel-campaign). Results are reported for the two parts separately.
- **IMC'25's `time` is free text from screenshots.** Only 354 of 30,971 values are ISO dates, and 5,049 contain a year (mostly 2019–2023). A reliable temporal split isn't possible without a validated parser, so no temporal claims are made on IMC'25.

### 6. Campaign identity (SP'24)

- **Matching:** 86% of messages (58,478 / 68,029) match one of the authors' campaign templates after normalisation.
- **Granularity:** the authors' 35,128 campaigns collapse into 12,756 text templates, because they split campaigns by URL and time. 61% of their campaigns have a single message, and the median campaign lasts under a day.
- **Grouping:** this project groups by our near-duplicate clusters (2,464), which is coarser and therefore safer against leakage.

### 7. Other validation findings

- **SP'24:** the `phishing_messages.csv` header names 6 columns, but all 68,029 rows have 7. `pandas.read_csv` silently shifts the columns, so the adapter parses positionally.
- **Conflicting labels in duplicate groups:** IMC'25 47 groups, Mishra & Soni 37, SmishTank 6, Super SMS 1.
- **Encoding:** the SmishTank mirror is cp1252, and Super SMS is not valid UTF-8; both are decoded with a recorded fallback.
- **PII indicators** (heuristic counts; raw data untouched):

  | Dataset | Records flagged |
  |---|---|
  | IMC'25 | 25 Indian phone numbers, 16 Aadhaar-like, 16 card-like (Luhn), 22 IFSC-like, 10 UPI IDs |
  | Super SMS | 433 Indian phone numbers, 191 Aadhaar-like |
  | SP'24 | 41,730 contain URLs (unmasked) |

  Nothing is redistributed from this repository: raw data stays out of git, and only manifests and digests are committed.

## Split definitions (v1)

| Split id | Data | Purpose | Leakage control | Sizes (records) |
|---|---|---|---|---|
| `imc25_group_v1` | IMC'25 | In-distribution scam type / lures | whole near-dup clusters per side (70/10/20) | train 23,651 / val 3,378 / test 6,759 |
| `imc25_holdout_delivery_v1` | IMC'25 | Unseen family | family held out; its near-duplicates purged | train 29,761 / purged 217 / test 3,810 |
| `imc25_holdout_government_v1` | IMC'25 | Unseen family | as above | train 30,064 / purged 476 / test 3,248 |
| `sp24_temporal_v1` | SP'24 | Detection over time; known vs novel campaigns | time order; test split by cluster novelty | train 47,620 / val 6,801 / test 3,084 seen + 10,524 novel |
| `india_spam_sms_junioralive_group_v1` | India SMS (junioralive) | Indian legitimate + promotional negatives | near-dup grouping | train 1,586 / val 227 / test 454 |
| `<dataset>_group_v1` | UCI, MOZ (after official download + licence check) | negatives / out-of-domain | near-dup grouping | built automatically when registered |

Two further controls are applied when SFT files are built (`sentinel/build_sft_real.py`):
- Near-duplicates are recomputed across **all** sources, and any test example that is a near-duplicate of a train or validation example is dropped (690 from the IMC'25 test, 37 from SP'24 and 10 from the Indian negatives, after harmonised masking).
- Evaluation-only sources never reach train or validation.
