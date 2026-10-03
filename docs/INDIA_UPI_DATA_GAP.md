# India / UPI data gap

**Finding.** No public dataset I could find combines all five of:

**Indian scam messages + UPI context + transaction outcome + temporal session order + payee identity/graph**

Nothing in this repository is presented as one. Simulator data stays labelled SYNTHETIC, and it is never relabelled as real Indian UPI data.

## What exists (verified 2026-10-03)

| Source | What it gives | What it lacks |
|---|---|---|
| IMC'25 smishing, India slice | 3,729 real reported scam SMS sent from Indian networks (98% English, 49 Hindi). Mostly banking/KYC lures: SBI/YONO, PAN update, rewards. 136 of these mention a UPI app by name (`upi`, Paytm, PhonePe, GPay, BHIM; measured) | No legitimate messages, sessions, payments, outcomes or payee IDs. Text is pseudonymised, and transcribed and labelled by GPT-4o |
| India spam SMS (junioralive, MIT) | 2,267 Indian SMS: 1,522 legitimate and 745 operator/retail promotions (measured); crowd-sourced via a Google Form | No scams, sessions or payments; labelling and consent undocumented. **The only clearly licensed Indian legitimate SMS found**: used as negatives |
| Precog / IIIT-Delhi Indian SMS (by request) | Hindi + English crowd-sourced ham/spam (~2,000 per a redistributor) | Access by request; terms not yet seen; spam likely mostly promotions |
| PhonePe Pulse (CDLA-Permissive-2.0) | Real aggregate UPI volumes, amounts and categories by state/district/quarter (one app) | No fraud labels, transactions or payees; useful to calibrate the simulator |
| NUS SMS Corpus, India users | 8,560 real personal SMS from 67 Indian volunteers (2010–2011) | No licence; personal chat rather than bank/merchant/UPI SMS; old |
| RevisedIndian SMS (GitHub, 2018) | 4,567 messages in English, Telugu, Hindi and some Hinglish | No provenance or licence; "spam" is mostly advertising; rejected |
| ICFD-31k (IJCAI 2026) | 31,000 Indian English/Hinglish scam-call dialogues | **Synthetic**, restricted licence: adversarial testing only |
| Hinglish scam text (Hugging Face) | About 63 hand-written Hinglish rows | Too small; hand-written |
| Hindi/Hinglish GitHub sets (gupta7050, India Cyber Scam Hinglish, SMS-Suraksha) | Thousands of rows | **Measured:** 101 unique texts per 5,000 rows; 743 unique per 10,000; machine-translated. Rejected as real data |
| I4C / NCRP figures | National complaint and loss totals (in parliamentary answers) | Aggregates only; no record-level data |
| NPCI / RBI publications | UPI volumes and aggregate fraud statistics | Aggregates only; no messages, sessions or payees |

Measured language reality across all real scam data in the repo: Hindi 175 rows (IMC'25 labels), 115 rows containing Devanagari, and under 30 Hinglish *candidates* (lexical heuristic, not labels). **Hindi, Hinglish and Indian-scam detection claims are not supported by real data today.** The Hindi and Hinglish in the simulator are template-generated and stay SYNTHETIC.

## Why the existing data is insufficient

1. **No sessions.** Every real scam dataset is a single message, so the core idea (a scam unfolds across messages, calls, screen-share, payee creation and payment) can't be learned or tested on real data.
2. **No outcomes.** Nobody publishes whether the victim paid, how much, or whether an alert changed the outcome. The alert policy's real effect can't be measured.
3. **No payees.** Real UPI VPAs and mule-account graphs are confidential bank and NPCI data.
4. **Almost no modern legitimate traffic.** The clearly licensed legitimate SMS are UCI (2012 UK/Singapore) and 1,522 Indian messages from a small community collection. Real Indian bank, OTP, merchant and DLT-registered SMS, the messages a deployed system must *not* flag, are absent. That is the data that decides false alerts.
5. **Language.** Real Indian scams are often in Hindi, regional languages or romanised Hinglish. Public real data has almost none.

## Privacy and legal barriers

- **Personal data law:** the Digital Personal Data Protection Act, 2023 and its rules require purpose-specific, informed consent and data minimisation for personal data. Messages and transactions are personal data.
- **Payment data:** RBI's 2018 directive on storage of payment system data keeps payment data in India and with regulated entities, so researchers can't simply obtain transaction logs.
- **Bank secrecy and NPCI rules** restrict sharing account-level and VPA-level data.
- **Third parties:** messages contain other people's data (senders, contacts), so the donor's own consent doesn't cover it.
- **Victim sensitivity:** fraud victims are a vulnerable group, and collection must avoid re-traumatising them or exposing them.

## What a future consented dataset needs

**Unit:** a *session*, meaning all events on one victim's device in a window around a suspected scam, or a matched legitimate session.

**Annotation schema (aligned with Chakravyuh's event types):**

| Field | Values / notes |
|---|---|
| `session_id` | random; no device or person identifier |
| `events[]` | ordered: `t` (seconds from session start), `type` ∈ MSG_RECV, MSG_SENT, CALL, SCREEN_SHARE, REMOTE_APP, LINK_OPEN, APK_INSTALL, UPI_OPEN, PAYEE_NEW, FD_BREAK, PAY, RECV |
| `text` | redacted on device; or only on-device tags (`client_tags`) when text can't leave the phone |
| `sender_class` | saved contact / unknown number / DLT-registered header / short code (no raw numbers) |
| `payee` | salted hash of the VPA, plus account age band and first-time flag; never the raw VPA |
| `amount_band` | band relative to the user's usual amount (not the exact amount) |
| `session_label` | scam / legitimate / unsure, assigned by trained annotators with a written guideline |
| `scam_family` | Chakravyuh taxonomy (investment_group, task_job, digital_arrest, fake_kyc, ...) + "other" |
| `stage` per event | contact / hook / trust / pressure / payment_ask / payment / cashout |
| `tactics` per message | the 13-tactic taxonomy (multi-label), with an inter-annotator agreement target of κ ≥ 0.7 |
| `outcome` | paid / not paid / reversed / reported; amount band lost |
| `report_link` | whether reported to 1930 / NCRP / Chakshu (yes/no, no case numbers) |
| `language` | per message, including romanised Hindi |
| `consent_version`, `collected_at`, `region` (state level) | provenance |

**Collection requirements:**
- **Who:** consenting adult volunteers, through a bank, a consumer organisation or a research partner. The reporting channels (1930 helpline, Sanchar Saathi / Chakshu) are possible partners, not data sources.
- **Matched negatives:** legitimate sessions from the same volunteers (salary credit, rent, family transfers, merchant payments, bank OTPs), so false alerts can be measured.
- **Coverage:** at least Hindi, English, Hinglish and 3–4 regional languages; rural and urban; age groups (older adults are a key group).
- **Time:** collection across at least 12 months, for temporal and new-family testing.

**Ethical and privacy requirements:**
- Ethics committee / IRB approval before collection; written consent in the participant's language; withdrawal at any time with deletion.
- On-device redaction before upload: names, numbers, VPAs, account numbers, Aadhaar and PAN removed or hashed with a per-study salt.
- A data protection impact assessment, plus storage in India with access control, an audit log and a fixed retention period.
- Victims are never contacted for collection because of their loss; participation is never a condition of support.
- Release only under a data-use agreement. Any public release is tactic and sequence level, never full text (consistent with `SECURITY.md`).
- A datasheet documenting the collection, consent, annotation guideline, agreement scores and known biases.

## Until then

- **Real-data track:** message-level models only (scam type, lures, scam vs legitimate) on licensed global data, with honest language and geography statements.
- **Synthetic track:** ScamSeq, payee graph, fusion and alert policy on the Chakravyuh simulator, reported separately and labelled SYNTHETIC.
- **Indian check:** the IMC'25 India slice serves as a *real Indian scam-message* test subset, recall only, because it has no Indian negatives.
