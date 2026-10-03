# Chakravyuh

**Scam-session detection for UPI, banking and wallets.** Chakravyuh scores the whole scam *session* (the messages, calls, screen shares and payee changes that lead up to a payment), not just the payment. It warns people before money moves, and it learns *when* to speak so legitimate users aren't buried in alerts.

Problem statement: *AI-Driven Scam Pattern Recognition. Detect emerging AI-enabled scam workflows in UPI, banking, or wallet contexts and deliver timely, useful alerts without creating alert fatigue.*

## What's inside

| Part | What it does |
| --- | --- |
| **Chakravyuh simulator** (`backend/chakravyuh/sim`) | Multi-agent simulator: attacker agents run scam scripts in English, Hindi and Hinglish; victim agents with different vulnerability decide whether to pay; a UPI-style payment sandbox moves money through mule rings. An evolutionary loop keeps breeding scams the current defender misses. |
| **Tactic tagger** (`ml/tagger.py`) | Reads each message and returns tactics (authority, urgency, fear, greed…), kill-chain stage and a scam probability. Server-side stand-in for the on-device Sentinel SLM. |
| **ScamSeq** (`ml/scamseq.py`) | A 235k-parameter causal transformer over session events. Predicts scam probability, the scammer's *next* step, and time until payment. |
| **Payee graph model** (`ml/payee_risk.py`) | GraphSAGE with time-decay aggregation on the transaction graph to score mule accounts. Plain PyTorch, no PyG. |
| **Fusion + calibration** (`ml/fusion.py`) | Combines the signals, calibrates them (Platt scaling) and sets session-level conformal thresholds: a stated cap on how many legitimate sessions each alert level may touch. |
| **Alert policy** (`ml/policy.py`) | A LinUCB contextual bandit trained in the simulator to choose the gentlest alert that stops the scam: nudge, check-in, cooling-off, hold. Lagrangian alert budget, and holds only when a payment is pending. |
| **Emerging-campaign detector** (`ml/campaigns.py`) | Flags risky sessions far from every known scam family, clusters them with HDBSCAN into campaign cards with a draft rule, and tracks tactic drift (PSI). |
| **Co-evolution loop** (`ml/coevolve.py`) | Attackers evolve against the defender, the defender fine-tunes on their tricks and recalibrates its alert thresholds, and an update ships only if it beats the current model. `make coevolve`. |
| **Public dataset** (`dataset/`) | 5,920 labelled sessions at tactic level (no message text or payee IDs) with splits for new wording, an unseen scam family and evolved scams. `make dataset` rebuilds it. |
| **Sentinel SLM kit** (`sentinel/`) | Builds the fine-tuning set and QLoRA-fine-tunes a 0.5–1.5B model (Qwen2.5) to output the same JSON on the phone; exports 4-bit GGUF. |
| **API** (`backend/app`) | FastAPI + SQLAlchemy (SQLite locally, PostgreSQL in production). Live sessions, alerts, payee risk, campaigns, arena, beta sign-up and feedback. |
| **Web app** (`frontend`) | React + Vite. Live session demo on a phone, attacker-vs-defender arena, campaign review, benchmark, beta page. |

## Results on simulated data

Every system sees the same sessions. Recall uses the threshold where 1% of legitimate sessions would be flagged.

| Test set | Keyword rules | Per-transaction model | Chakravyuh |
| --- | --- | --- | --- |
| Known scam types, **new wording** | 18% | 36% | **99.6%** |
| **Evolved** scams (later generations) | 16% | 88% | **100%** |
| A scam family **never seen** (fake e-challan) | 0% | 3.5% | **100%** |

- Chakravyuh warns **3.6 to 5 kill-chain stages before the payment**; a per-transaction model can only act at the payment.
- **No legitimate payment is paused** (levels 2–4 never fire on legitimate sessions in test). About 1% of legitimate sessions get a gentle nudge; they are genuine bank calls from unknown numbers with screen sharing, which verified sender IDs would resolve.
- **Arena:** attackers evolve until they get past the defender (detection falls from 100% to about 30% over 6 generations), then the defender fine-tunes on their tricks in about 12 seconds and catches about 92% of fresh variants.

These numbers come from simulated sessions. Real-world performance has to be measured with partner data during the beta (see `docs/BETA_TESTING.md`).

## Run it locally

You need Python 3.11+ and Node 20+.

```bash
make setup        # install backend + frontend dependencies
make api          # API on http://localhost:8000  (docs at /docs)
make web          # web app on http://localhost:5173
```

Trained models are already in `backend/artifacts`, so the app works straight away. To rebuild everything from scratch:

```bash
make data         # run the simulator (about 2 seconds)
make train        # train all models and write the benchmark (about 90 seconds on a laptop CPU)
make test         # backend tests + frontend type-check
```

Or run everything in Docker with PostgreSQL:

```bash
docker compose up --build    # web on http://localhost:8080, API on http://localhost:8000
```

### VS Code

Open the repo folder. Recommended extensions are suggested automatically. Run and debug configurations cover the API, the simulator and training (Run and Debug panel), and `Terminal > Run Task > dev: api + web` starts both servers.

Create a virtual environment in `backend/.venv` so the Python interpreter setting picks it up:

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## API in one minute

```bash
# Start a session, stream events into it, get a decision back for each event
curl -X POST localhost:8000/v1/sessions -H 'Content-Type: application/json' -d '{"language":"en"}'
curl -X POST localhost:8000/v1/sessions/<id>/events -H 'Content-Type: application/json' \
  -d '{"type":"MSG_RECV","text":"This is CBI. A parcel in your name contains illegal items."}'
```

Privacy mode: send `client_tags` (tactics and scam probability computed on the phone by the Sentinel SLM) instead of `text`, and the raw message never leaves the device. Set `STORE_MESSAGE_TEXT=false` so text is scored in memory only.

## More realistic data with an LLM

The simulator runs offline from a template library. Point it at any OpenAI-compatible endpoint (Groq, a local Ollama, vLLM) and the attacker agents paraphrase every message, which makes the data much harder:

```bash
export CHAKRAVYUH_LLM_BASE_URL=http://localhost:11434/v1 CHAKRAVYUH_LLM_MODEL=qwen2.5:7b
LLM_RATE=0.5 make data && make train
```

## Responsible release

The attacker engine is for defenders. Generated data is released at the tactic level, the mutation engine is not published as a ready-made scam generator, and alert texts are fixed vetted templates, so no model output can tell a user that a scam is safe. See `docs/SECURITY.md`.

## Docs

- `docs/DEPLOY.md`: deploying to Render (or any Docker host)
- `docs/BETA_TESTING.md`: running the alpha and beta
- `docs/SECURITY.md`: threat model and responsible release
- `sentinel/README.md`: fine-tuning the on-device SLM
