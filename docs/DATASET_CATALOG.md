# Dataset catalog (Phase 1)

Every dataset below has a manifest in `data/registry/<dataset_id>.json` with provenance, licence,
access status and SHA-256 digests. Counts marked **measured** were computed on the files with
`scripts/validate_real_dataset.py` and `scripts/leakage_audit.py`. Other counts come from the paper or
the source page and are labelled that way. Audit date: 2026-10-03.

## Access status

| Status | Meaning here |
|---|---|
| **AVAILABLE_NOW** | Original authors' GitHub release, fetched at a pinned commit in this environment; SHA-256 recorded |
| **GITHUB_MIRROR_AVAILABLE** | Only a third-party GitHub copy is reachable from here; used for the leakage audit, never for training |
| **REQUIRES_LOCAL_DOWNLOAD** | Official source is blocked here (Hugging Face, UCI, Mendeley, Kaggle, ftc.gov, Google Drive). Download on your laptop, then `scripts/fetch_real_datasets.py register` checks and pins it |
| **BLOCKED** | No legitimate route to the data at the moment |
| **REJECTED** | Not used, with the reason stated |

Licence status is tracked separately: CLEAR, NON_COMMERCIAL, RESTRICTED, UNRESOLVED (no licence found), CONFLICTING.
A dataset may only enter training with a CLEAR licence (or a restricted one whose terms we meet). It must also come from the original source with its SHA-256 verified.

## Catalog

| Dataset | Source | Licence | Access | Size | Language | Geography | Real / synthetic | Component | Task | Key limitations |
|---|---|---|---|---|---|---|---|---|---|---|
| `imc25_smishing` | Agarwal et al., ACM IMC 2025 | CC-BY-4.0 (CLEAR) | AVAILABLE_NOW | 33,869 msgs (measured); 23,256 unique after normalisation | 66 languages; English 65%, Spanish 14%, Hindi 175 rows | Global; India the most common sending network (3,729 rows) | REAL (user reports) | Message tagger, campaign detector, Sentinel | Scam type (8 classes), lure tagging (7), scam detection (positives) | **No legitimate messages**; GPT-4o transcription and labels (κ 0.93 type / 0.70 lures vs humans, n=150); free-text times; 82% contain mask tokens |
| `sp24_gateway_phishing` | Nahapetyan et al., IEEE S&P 2024 | MIT (CLEAR) | AVAILABLE_NOW | 68,029 msgs; 35,128 campaigns (measured) | ~50% English, French 17%, Japanese 10% (langid, first 20k) | Public SMS gateways; UK/US heavy | REAL | Campaign detector, tagger (eval) | Novel-campaign detection over time; cross-source scam recall | Positive-only; URL-reputation labels include gambling promos; 12,767 unique texts; 73% of messages in Apr–May 2023; broken CSV header |
| `uci_sms_spam` | Almeida & Gómez Hidalgo, UCI 2012 | CC-BY-4.0 per UCI page (CLEAR) | REQUIRES_LOCAL_DOWNLOAD (mirror audited) | 5,574 (4,827 ham / 747 spam) | English | UK, Singapore | REAL | Tagger (legitimate negatives only) | Scam-vs-legit negatives | 2012 text; 'spam' ≠ scam; 97.5% of it is inside Mishra & Soni, 89.9% inside Super SMS |
| `india_spam_sms_junioralive` | junioralive (community, 2024) | MIT (CLEAR) | AVAILABLE_NOW | 2,267 (1,522 ham / 745 promo "spam"; measured), 1,920 unique | English, some romanised Hindi | India (Airtel, Vi, Jio, CERT-In) | REAL (crowd-sourced via Google Form) | Tagger, Sentinel (negatives) | **Indian legitimate + promotional negatives** | Provenance and labelling undocumented; "spam" = promotions, not fraud; personal messages unmasked |
| `precog_indian_sms` | Precog, IIIT-Delhi | set by the authors on request (UNRESOLVED) | REQUIRES_LOCAL_DOWNLOAD (request form) | ~2,000 (1,000 ham / 1,000 spam per a redistributor) | Hindi + English | India | REAL (crowd-sourced) | Tagger (evaluation) | Hindi/English scam-vs-legit test | Only via request; terms unseen; unlicensed GitHub copy not used |
| `phonepe_pulse` | PhonePe | CDLA-Permissive-2.0 (CLEAR) | AVAILABLE_NOW | 11,184 aggregate JSON files | — | India | AGGREGATE_REPORTS | Simulator calibration, priors | UPI volume/amount/category by state and quarter | No fraud labels; no transactions or payees; one app |
| `moz_smishing` | Ali et al., AfricaNLP 2025 | Paper CC-BY-4.0; **dataset licence UNRESOLVED** (an earlier pass read the HF card as creativeml-openrail-m) | REQUIRES_LOCAL_DOWNLOAD (Hugging Face) | 2,561 (552 smishing / 2,009 legit) per paper | Portuguese | Mozambique | REAL (crowd-sourced) | Tagger, Sentinel (out-of-domain test) | Mobile-money smishing vs legit | **Not Indian**; small; licence and collection period unknown |
| `smishtank` | Timko & Rahman 2024 | UNRESOLVED | REQUIRES_LOCAL_DOWNLOAD (mirror audited) | 1,062 (measured on mirror) | English | USA | REAL | — (audit) | — | 49.3% near-duplicated in IMC'25; recipient names in OCR text |
| `mishra_soni_smishing` | Mishra & Soni, Mendeley 2022 | UNRESOLVED | REQUIRES_LOCAL_DOWNLOAD (mirror audited) | 5,971 | English | mixed | REAL | — (audit) | — | 89% near-duplicate of UCI; not an independent source |
| `super_sms` | Salman et al., IEEE Access 2024 | none in repo (UNRESOLVED) | AVAILABLE_NOW | 67,008 labelled (measured) | 96% English | aggregate | REAL (aggregate) | — (audit) | — | Contains UCI and 52% of NUS; spam not scam; no licence |
| `nus_sms_corpus` | Chen & Kan, LRE 2013 | none (citation request) (UNRESOLVED) | AVAILABLE_NOW | 55,835 (India 8,560) | English | Singapore, India, US, Sri Lanka | REAL (donated personal SMS) | — (would be legit negatives) | — | No licence; 2010–2011 personal chat, not bank/merchant SMS |
| `spamhunter` | Tang et al., CCS 2022 | none (UNRESOLVED) | AVAILABLE_NOW | 25,826 texts (repo) | multilingual | global | REAL | — | — | No licence; lemmatised; only 947 labelled |
| `scambaiting_email` | Chen, Wang, Edwards, EuroS&P 2023 | none (UNRESOLVED) | AVAILABLE_NOW | 658 conversations / 37,501 messages (repo) | English | global | REAL | (research only) | Multi-turn stage annotation study | E-mail advance-fee, not SMS/UPI; unmasked PII |
| `teleantifraud` | Ma et al., ACM MM 2025 | Apache-2.0 | AVAILABLE_NOW (10,006 in repo) | 10,006 dialogues | Chinese | China | **LLM_GENERATED** | Synthetic track only | — | Generated by DeepSeek-V2.5 |
| `icfd_31k` | Ahuja et al., IJCAI 2026 | restricted, non-commercial | REQUIRES_LOCAL_DOWNLOAD | 31,000 dialogues | Indian English / Hinglish | India | **SYNTHETIC** | Synthetic/adversarial track only | — | Synthetic |
| `ftc_csn_2023` | US FTC | US government work (CLEAR) | REQUIRES_LOCAL_DOWNLOAD | aggregate tables | — | USA | AGGREGATE_REPORTS | Taxonomy / trend comparison | — | Unverified consumer reports |
| `ftc_csn_2024` | US FTC | US government work (CLEAR) | REQUIRES_LOCAL_DOWNLOAD | aggregate tables | — | USA | AGGREGATE_REPORTS | Taxonomy / priors only | Category and channel trends | **Unverified consumer reports**; aggregates, not transactions |
| `elliptic_plus_plus` | Elmougy & Liu, KDD 2023 | UNRESOLVED | REQUIRES_LOCAL_DOWNLOAD (Google Drive; repo has LFS stubs) | ~200k txs + wallets (paper) | — | Bitcoin | REAL | Payee-graph *method* benchmark only | Illicit node classification | Crypto AML, not UPI payees |
| `paysim` | Lopez-Rojas 2016 | UNRESOLVED (Kaggle) | REQUIRES_LOCAL_DOWNLOAD | ~6.4M rows (Kaggle) | — | simulated | **SYNTHETIC** | Synthetic track only | — | Simulation: never "real transactions" |
| `chakravyuh_simulator` | this project | n/a | AVAILABLE_NOW | per build | en / hi / hinglish templates | simulated India/UPI | **SYNTHETIC** | ScamSeq, payee graph, fusion, policy (synthetic track) | — | Results never reported as real-world |
| `sting9` | Sting9 Research Initiative | **CONFLICTING** (repo LICENSE.md = ODC-BY-NC "with clarifications"; site/API = CC0) | REJECTED | dump contains no data | multilingual | global | MIXED | — | — | Seeded from Mishra & Soni and another existing file; no versioned release |
| `chifraud` | Tang et al., COLING 2025 | CC BY-NC 4.0 (metadata) | REJECTED | 411,434 | Chinese | China | REAL | — | — | Out of language/geography; non-commercial |
| `care_gnn_amazon_yelp` | Dou et al., CIKM 2020 | Apache-2.0 (code) | REJECTED | — | — | US | REAL | — | — | Review fraud, not payments |
| `revised_indian_sms` | student repo 2018 | none | REJECTED | 4,567 | En / Hi / Te / Hinglish | India | REAL? | — | — | No provenance; 'spam' is ads; unmasked numbers |
| `exais_sms` | Onashoga et al. 2015 | none | REJECTED | 5,240 | English | Nigeria | REAL | — | — | Malformed CSVs, promotions as spam |
| `ieee_cis_fraud` | Vesta / Kaggle | competition rules | REJECTED | — | — | — | REAL | — | — | Card e-commerce, competition-only terms |
| `hindi_hinglish_gupta7050` | GitHub (gupta7050) | none | REJECTED | 2 × 5,000 rows, **101 unique texts each** (measured) | Hindi, Hinglish | India | SYNTHETIC (templated) | — | — | Templated duplicates |
| `india_cyber_scam_hinglish` | GitHub re-host | none | REJECTED | 10,000 rows, **743 unique** (measured) | Hinglish | India | SYNTHETIC | (synthetic track at most) | — | Synthetic, duplicated |
| `sms_suraksha` | GitHub (vanshbeni) | none | REJECTED | — | Indian languages | — | SYNTHETIC (machine-translated, per README) | — | — | Translation of an English corpus: leaks into splits |
| `bank_account_fraud_baf` | Feedzai, NeurIPS 2022 | CC BY-NC-ND 4.0 (per earlier pass) | REJECTED | — | — | — | SYNTHETIC | — | — | Account-opening, not payments |

Also checked and not registered: ExpertSMS (nothing found anywhere); the Hindi spam SMS set (IEEE DataPort only); the Hinglish scam text set on Hugging Face (only about 63 hand-written Hinglish rows); I4C/NCRP (only aggregate counts in parliamentary answers); Korean and Bangladeshi smishing sets (out of scope, and only third-party copies).

## Status lists

- **AVAILABLE_NOW (licence CLEAR, usable for training after your approval):** `imc25_smishing`, `sp24_gateway_phishing`, `india_spam_sms_junioralive`.
- **AVAILABLE_NOW, context only (aggregates):** `phonepe_pulse`.
- **AVAILABLE_NOW but licence unresolved (audit only):** `super_sms`, `nus_sms_corpus`, `spamhunter`, `scambaiting_email`.
- **AVAILABLE_NOW, synthetic track only:** `teleantifraud`, `chakravyuh_simulator`.
- **GITHUB_MIRROR_AVAILABLE (audited from third-party copies):** `uci_sms_spam`, `smishtank`, `mishra_soni_smishing` (each also REQUIRES_LOCAL_DOWNLOAD for the official file).
- **REQUIRES_LOCAL_DOWNLOAD:** `uci_sms_spam`, `moz_smishing`, `precog_indian_sms` (request), `smishtank`, `mishra_soni_smishing`, `ftc_csn_2024`, `ftc_csn_2023`, `elliptic_plus_plus`, `paysim` (synthetic), `icfd_31k` (synthetic).
- **BLOCKED:** none with a legitimate route; Sting9 is effectively blocked (no data published) and is listed as rejected.
- **REJECTED:** `sting9`, `chifraud`, `care_gnn_amazon_yelp`, `revised_indian_sms`, `exais_sms`, `ieee_cis_fraud`, `hindi_hinglish_gupta7050`, `india_cyber_scam_hinglish`, `sms_suraksha`, `bank_account_fraud_baf`.

## Real-data model mapping

| Dataset | Data type | Real / synthetic | Component | Task | Label | Features | Limitations |
|---|---|---|---|---|---|---|---|
| imc25_smishing | single messages | REAL | Message tagger | Scam-type classification (7 scam types + spam) | `scam_type` (GPT-4o, κ 0.93) | masked text, language | Positive-only; LLM labels |
| imc25_smishing | single messages | REAL | Message tagger | Lure / tactic tagging | `lure_principles` → authority, urgency, greed, social_proof, reciprocity (5 of our 13 tactics) | masked text | κ 0.70 weak labels; 8 of our tactics (fear, secrecy, isolation, remote_access, credential_request, payment_request, trust_building, link_click) have **no real labels** |
| imc25_smishing + india_spam_sms_junioralive (+ uci_sms_spam official) | single messages | REAL | Message tagger, Sentinel | Scam vs legitimate vs promotional | scam / legit / spam | masked text | Only 1,522 Indian legitimate messages; UCI is 2012 UK/Singapore; source-shortcut risk |
| phonepe_pulse | aggregate UPI statistics | AGGREGATE_REPORTS | Simulator (synthetic track) | Calibrate amount / category / regional distributions | none | counts, amounts | Not fraud data |
| sp24_gateway_phishing | messages + campaigns + timestamps | REAL | Campaign detector | Novel-campaign detection on a time split | template cluster; authors' campaign IDs for 86% of messages | masked text, time | Gateway numbers, not victims; positive-only |
| sp24_gateway_phishing | messages | REAL | Tagger, Sentinel (evaluation) | Cross-source scam recall | scam | masked text | Recall only (no negatives) |
| moz_smishing (after licence check) | single messages | REAL | Tagger, Sentinel (evaluation) | Out-of-domain scam vs legit | smishing / ham | text | Portuguese/Mozambique |
| ftc_csn_2024 | aggregate complaint tables | AGGREGATE_REPORTS | Taxonomy, priors | Category/channel/payment trends | none | counts | Unverified consumer reports; never training labels |
| elliptic_plus_plus | transaction graph | REAL | Payee graph (method benchmark only) | Illicit node classification | illicit / licit / unknown | graph + node features | Bitcoin, not UPI payees |
| scambaiting_email | multi-turn conversations | REAL | (research) ScamSeq stage-tagging feasibility | none yet | — | e-mail text, turn order | Not SMS/UPI; no licence; would need annotation |
| chakravyuh_simulator | sessions, ledger, graph | SYNTHETIC | ScamSeq, payee graph, fusion, policy | all (synthetic track) | simulator ground truth | full session | Synthetic only |

What is **not** mapped, and why:
- **ScamSeq:** no real dataset has victim-side sessions (messages + calls + app events + payments in order). Real-data sequence training is currently unsupported by available public data.
- **Payee graph:** no public dataset has real UPI or bank payee relationships. Elliptic++ can test the graph method only; PaySim stays SYNTHETIC.
- **Fusion and alert policy:** real calibration needs session-level outcomes. Only message-level calibration is possible on real data.

Sources: the [IMC'25 paper](https://discovery.ucl.ac.uk/10214522/1/Agarwal_IMC_2025_Smishing.pdf), the [MOZ-Smishing paper](https://aclanthology.org/2025.africanlp-1.23), the [Sting9 dataset page](https://sting9.org/dataset) and [organisation](https://github.com/sting9-research), the [FTC Data Book 2024](https://www.ftc.gov/reports/consumer-sentinel-network-data-book-2024), the [SmishTank paper](https://arxiv.org/html/2402.18430v2), the [UCI SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/), and the repositories named in each manifest.
