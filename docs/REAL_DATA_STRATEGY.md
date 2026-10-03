# Real-data strategy

## Principles

1. **Two tracks, never merged.** `REAL` results come from public real-world data. `SYNTHETIC` results come from the Chakravyuh simulator, PaySim, LLM-generated dialogues and synthetic Hinglish. Each report names its track, and no table mixes the two.
2. **Acquired means verified.**
   - A dataset counts as acquired only when its files are on disk with a SHA-256 recorded in its manifest.
   - Finding the paper or download page doesn't count.
   - A third-party mirror never counts for training.
3. **Licence gate.** Training needs `license_status` CLEAR, or RESTRICTED terms we meet. UNRESOLVED and CONFLICTING datasets are audited, never trained on.
4. **Raw data is immutable.** Files are copied into `data/real/<type>/<id>/raw/` and made read-only. All cleaning happens in adapters that read raw files and write `data/processed/`.
5. **Leakage before accuracy.** No real-data number is reported unless it comes from a split that groups near-duplicates (see `DATA_LEAKAGE_AUDIT.md`).
6. **Prefer original sources** over convenience copies (Kaggle re-uploads, aggregator repos).

## Access constraint

From this environment only GitHub (anonymous `git` clones) and PyPI are reachable. Hugging Face, Zenodo, UCI, Mendeley, Kaggle, Figshare, Google Drive, arXiv and ftc.gov are not.

Datasets on those hosts are marked `REQUIRES_LOCAL_DOWNLOAD`. You download them on your laptop, and `scripts/fetch_real_datasets.py register` checks and pins them.

## Directory layout

```
data/
  registry/<dataset_id>.json      manifest per dataset (committed)
  real/
    messages/<id>/raw/            raw files, read-only, git-ignored
    transactions/ graphs/ campaigns/ complaints/ dialogues/
  synthetic/simulator/ evolution/ synthetic data only (git-ignored)
  processed/<id>.msg-v1.jsonl     canonical records (git-ignored)
  splits/<split_id>.json          leakage-safe assignments + SPLITS.json index (git-ignored)
  reports/                        validation and leakage JSON (regenerated)
```

## Manifest fields

**Required by the spec:**
- **Identity:** `dataset_id`, `name`, `source`, `official_url`, `paper`.
- **Terms and version:** `license`, `version`, `download_date`, `sha256` (file → digest).
- **Content:** `sample_count`, `schema`, `label_schema`, `geography`, `language`.
- **Collection:** `collection_period`, `collection_method`, `real_or_synthetic`.
- **Handling:** `pii_status`, `preprocessing_version`, `provenance`, `limitations`.

**Governance fields:**
- **Classification:** `data_type`, `access_status`, `license_status`, `original_or_mirror`.
- **Retrieval:** `fetch` (pinned git commit or local-download instructions; optional `mirror`), `mirror_sha256`.
- **Use:** `adapter`, `components`, `training_allowed`, `training_note`.

`registry.manifest_problems()` enforces the rules:
- Every field is present.
- Enumerations are valid.
- `training_allowed` can't be true with an unresolved or conflicting licence.
- `training_allowed` can't be true for non-real data outside the simulator track.

## Canonical message schema (`msg-v1`)

**Fields:**
- **Identity:** `record_id`, `dataset_id`, `source_row`.
- **Content:** `text` (as released), `text_masked` (shared masking).
- **Labels:** `label` ∈ {scam, legit, spam, unknown}, `label_raw`, `scam_type`, `lures`, `tactics` (mapped from lures where an equivalent exists), `label_quality`.
- **Context:** `language`, `country`.
- **Time:** `timestamp`, `timestamp_quality` (unix_seconds / report_time / free_text / none), `year`.
- **Grouping:** `sender_type`, `campaign_id`, `near_dup_cluster`, `exact_group`.
- **Handling:** `audit_only`, `real_or_synthetic`, `preprocessing_version`.

**Label policy:** `spam` (unsolicited or marketing, not shown to be fraud) is never folded into `scam` or `legit`. UCI "spam" is not scam. IMC'25 "spam" is its own class.

## Workflow

```bash
python scripts/fetch_real_datasets.py status
python scripts/fetch_real_datasets.py fetch imc25_smishing sp24_gateway_phishing india_spam_sms_junioralive   # pinned, SHA-256 checked
python scripts/fetch_real_datasets.py register uci_sms_spam --from ~/Downloads/smsspamcollection --pin
python scripts/validate_real_dataset.py --all
python scripts/leakage_audit.py
python scripts/prepare_real_splits.py
python sentinel/build_sft_real.py --config sentinel/configs/sentinel_real_v1.json
```

The same steps are available as Make targets: `data-real`, `validate-real`, `audit-leakage`, `splits-real`, `sft-real`.

## Local downloads needed from you

| Dataset | Get it from | Then |
|---|---|---|
| UCI SMS Spam Collection (official) | https://archive.ics.uci.edu/dataset/228/sms+spam+collection → `smsspamcollection.zip` | unzip, then `register uci_sms_spam --from <folder> --pin`. If its SHA-256 equals the audited mirror digest, the manifest shows it |
| MOZ-Smishing | `huggingface-cli download MOZNLP/MOZ-Smishing --repo-type dataset --local-dir ~/Downloads/moz` | read the dataset card licence and tell me; I update the manifest; then `register moz_smishing ...` |
| Precog / IIIT-Delhi Indian SMS (Hindi + English) | request at http://precog.iiitd.edu.in/requester.php?dataset=smsspam | record the authors' terms; then register |
| SmishTank (optional) | https://smishtank.com/dataset | confirm the licence first |
| FTC Data Book 2024 CSVs (optional, context only) | https://www.ftc.gov/system/files/ftc_gov/data/csn-data-book-2024-csv.zip | `register ftc_csn_2024 --from <folder> --pin` |
| Elliptic++ (optional, graph method benchmark) | the Google Drive folder in https://github.com/git-disl/EllipticPlusPlus | confirm the terms first |

## How each component uses real data

See the model mapping in `DATASET_CATALOG.md` and the experiments in `REAL_TRAINING_PLAN.md`. In short:
- **Message tagger and Sentinel:** trainable on real data.
- **Campaign detector:** testable over time on SP'24.
- **ScamSeq, payee graph, fusion and policy:** no public real data supports them, so they stay on the synthetic track (`INDIA_UPI_DATA_GAP.md`).
