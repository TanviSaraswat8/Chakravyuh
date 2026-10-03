# Chakravyuh — Current Architecture (Phase 0 audit)

Audit of commit `58438cb` (main), 2026-10-03. This document describes what exists **today**, before the
real-data, agent-canvas and security-hardening work. Nothing was changed while writing it.
The access-control findings in §8 and §13 have since been fixed: see `SECURITY_REMEDIATION.md`.

Status words used below:

- **Implemented** — code exists and is covered by tests or the Docker validation run.
- **Partial** — code exists but is incomplete or untested for the stated purpose.
- **Not implemented** — no code.

---

## 1. Repository layout

```
backend/
  app/                FastAPI service (config, db, models, schemas, deps, routers/, services/)
  chakravyuh/sim/     Chakravyuh simulator: taxonomy, scripts, agents, payment sandbox, evolution
  chakravyuh/ml/      Tagger, ScamSeq, payee graph, fusion, alert policy, campaigns, engine, train, coevolve
  artifacts/          Committed trained models + metrics.json (trained 2026-10-03 03:40)
  data/               Generated simulator output (git-ignored; built at image build time)
  reports/            coevolution.json
  tests/              32 pytest tests (36 cases incl. parametrised) — SQLite and PostgreSQL 16
frontend/             React 19 + Vite 6 + TypeScript SPA, served by nginx in Docker
sentinel/             SLM fine-tuning kit (build_sft, finetune, evaluate) — no trained weights
dataset/              Public tactic-level export of simulated sessions (sessions.jsonl.gz + card)
scripts/              smoke_test.py, e2e_checks.py, validate_docker.ps1
docs/                 DEPLOY, BETA_TESTING, SECURITY (+ this file)
docker-compose*.yml, render.yaml, Makefile, .github/workflows/ci.yml, .vscode/
```

Approximate size: ~5,200 lines of Python/TypeScript in the app, simulator, models and UI.

## 2. Backend architecture

| Item | Detail | Status |
|---|---|---|
| Framework | FastAPI, Uvicorn, Pydantic v2 | Implemented |
| Startup | `lifespan`: `init_db()` (retries up to `DB_WAIT_SECONDS`=90 on `OperationalError`), then loads the model engine once | Implemented |
| Routers | `sessions`, `intel`, `demo`, `beta` under `/v1`; `/health` | Implemented |
| Services | `scoring.py` (engine wrapper, `score_session`), `alert_text.py` (vetted alert templates en/hi/hinglish), `demo.py` (scenarios, arena, adapt) | Implemented |
| Middleware | CORS only (`allow_credentials=True`, all methods/headers, origins from `CORS_ORIGINS`) | Partial |
| Rate limiting, security headers, request IDs, CSRF | — | Not implemented |

### API surface and current protection

| Route | Purpose | Auth today |
|---|---|---|
| `GET /health` | status + model status | none |
| `POST /v1/score` | stateless scoring of an event list | none |
| `POST /v1/sessions` | create live session | optional tester key (required only if `REQUIRE_API_KEY=true`) |
| `GET /v1/sessions` | list all sessions (up to 200) | **none** |
| `GET /v1/sessions/{sid}` | session with events (incl. message text when stored) | **none** |
| `POST /v1/sessions/{sid}/events` | add event, score, maybe alert | optional tester key; **no ownership check** |
| `POST /v1/sessions/{sid}/close` | close session | **none** |
| `POST /v1/alerts/{aid}/respond` | record user response | **none** |
| `GET /v1/meta`, `/v1/metrics`, `/v1/campaigns`, `/v1/payees/{vpa}/risk` | intel/read | none |
| `POST /v1/campaigns/refresh`, `PATCH /v1/campaigns/{cid}` | recluster / approve campaigns | **none** |
| `GET/POST /v1/demo/scenarios`, `/simulate`, `/arena` | demo + attacker evolution (bounded by schema) | none |
| `POST /v1/demo/arena/adapt?epochs=&persist=` | defender fine-tune; swaps the live model; `persist=true` overwrites `scamseq.pt` / `policy.json` | **none; `epochs` unbounded** |
| `POST /v1/beta/signup` | issue tester API key | none |
| `POST /v1/beta/feedback` | feedback | optional tester key |
| `GET /v1/beta/feedback`, `/v1/beta/testers` | admin lists | admin key or tester with role analyst/admin |

## 3. Frontend architecture

- React 19, react-router, Vite 6, TypeScript; one global stylesheet (`styles.css`). No state library.
- Pages: `/live` (scripted scam/legit replay on a phone mock), `/try` (type your own messages/events),
  `/arena` (attacker evolution rounds + defender adaptation), `/campaigns`, `/benchmark` (metrics.json),
  `/beta` (signup + feedback).
- Components: `Phone.tsx`, `Formation.tsx` (ring meter of kill-chain stages).
- `lib/api.ts`: fetch wrapper; reads the tester key from **`localStorage`** and sends it as `X-API-Key`.
- Dev/preview proxy `/v1` and `/health` to the API; in Docker nginx proxies the same paths.
- No graph/canvas library, no node editor, no websocket/SSE — UI state comes from request/response only.

## 4. Database

SQLAlchemy 2 models (`app/models.py`), created with `create_all` (no migrations tool):

| Table | Key columns | Notes |
|---|---|---|
| `beta_testers` | id, email (unique), name, org, role (`tester`/`analyst`/`admin`), cohort, **api_key (plaintext, unique)** | key stored unhashed |
| `sessions` | id, tester_id, source, channel, language, status, current_level, max_p, family_guess, outcome, embedding (JSON) | no owner enforcement in routes |
| `events` | session_id, idx, t, type, channel, **text**, tactics, attrs (JSON, may hold `_client_tags`), p, level, next_stage | text stored unless `STORE_MESSAGE_TEXT=false` |
| `alerts` | session_id, event_idx, level, action, reason_code, title, message, p, response | |
| `feedback` | tester_id, session_id, alert_id, page, rating, kind, comment | |
| `campaigns` | name, size, status, card (JSON) | |

Engines: SQLite (default/dev) and PostgreSQL 16 (Docker, Render). Tests run on both.
No field-level encryption, no audit table, no user/password/MFA/session tables.

## 5. Simulator (Chakravyuh) and agents

| Component | File | What it does |
|---|---|---|
| Taxonomy | `sim/taxonomy.py` | 13 tactics, 7 kill-chain stages, 8 scam families, 9 hard benign families, 12 event types, alert levels 0–4 |
| Script library | `sim/library.py` | per-family step scripts with stage, tactics, message variants (en/hi/hinglish), side events |
| Attacker agent | `sim/agents.py` (`Genome`, `build_script`, `run_session`) | genome = family, language, channel, text ops, extra tactics, borrowed benign opener (disguise), stage swaps/drops, amount and pace scale |
| Victim agent | `sim/agents.py` (`Victim.pay_probability`) | logistic pay model; warning penalty per alert level `[0, 0.8, 1.5, 3.0, 4.5]` |
| Payment world | `sim/sandbox.py` | UPI-like accounts, ledger, mule rings (layer1 → layer2 → exchange), background traffic |
| Mutations | `sim/mutations.py` | synonym, code-mix, obfuscation, typos, emoji |
| Optional LLM rewrite | `sim/llm.py` | OpenAI-compatible endpoint via `CHAKRAVYUH_LLM_*`; off by default |
| Evolution | `sim/evolution.py` | fitness `E[loss]·(1−p_detect) − λ·similarity`, mutation, crossover, novelty |
| Orchestrator / CLI | `sim/simulator.py` | writes `sessions.jsonl`, `ledger.csv`, `accounts.csv`, `evolution.json` with split hints `train_pool / test_seen / holdout_family / evolved`; last wording variant reserved for test |
| Public export | `sim/export_public.py` | tactic-level, text-free, hashed-id export (5,920 sessions) |

**All data the models are trained on is simulator output. There is no real-world data in the repo.**

## 6. Models (defender agents)

| Model | File | Method | Artifact |
|---|---|---|---|
| Message Tagger | `ml/tagger.py` | char n-gram TF-IDF + One-vs-Rest logistic regression (13 tactics + p_scam) | `tagger.pkl` (pickle) |
| Feature encoder | `ml/features.py` | per-event attribute vector (`ATTR_NAMES`), padding, train masks | — |
| ScamSeq | `ml/scamseq.py` | causal transformer (d=96, 3 layers, 4 heads, 235,402 params); focal BCE + next-stage CE + time-to-payment L1, early-detection weighting | `scamseq.pt` (state_dict, `torch.load`) |
| Payee graph | `ml/payee_risk.py` | GraphSAGE in plain PyTorch with time-decay adjacency over the sandbox ledger | `payee_scores.json` (scores only) |
| Fusion | `ml/fusion.py` | late-fusion logistic regression + Platt calibration; session-level conformal thresholds; ECE | `fusion.pkl` (pickle) |
| Alert policy | `ml/policy.py` | LinUCB contextual bandit, Lagrangian alert budget, level gates, payment-pending caps, paying-now safety floor, log(1+amount) reward | `policy.json` |
| Campaign detector | `ml/campaigns.py` | HDBSCAN over session embeddings + open-set prototype distance + PSI drift | `campaigns.json` |
| Engine | `ml/engine.py` | composes all of the above; `decide()` per step; `save/load` | loads **pickles without integrity check** |
| Training | `ml/train.py` | splits, baselines (rules, per-transaction LightGBM), benchmark → `metrics.json` | |
| Co-evolution | `ml/coevolve.py` | `Attacker` evolves vs live engine; `defend()` fine-tunes ScamSeq + refits tagger with replay, recalibrates gates, champion/challenger acceptance | `reports/coevolution.json` |

`torch` is 2.x, where `torch.load` defaults to `weights_only=True`; the pickle files are the unprotected path.
`artifacts/meta.json` records training time and report but **no file hashes**.

### Current measured results (synthetic only)

From `artifacts/metrics.json` — every number is on **simulator-generated data** and must not be presented as
real-world performance: recall at 1% false-alarm rate 99.6% (seen families, unseen wording), 100% (evolved
attacks), 100% (held-out family) vs rules 18.3%/15.8%/0% and per-transaction LightGBM 35.7%/88.3%/3.5%;
~11 legit nudges per 1,000 legit sessions, 0 legit payments paused; ECE 0.057–0.076; payee PR-AUC 1.0 on
1,711 sandbox accounts. The near-perfect scores reflect how separable the simulator still is.

## 7. Sentinel SLM pipeline

`sentinel/build_sft.py` builds chat-format SFT data from simulator sessions (JSON target: tactics, stage,
next stage, family, soft p_scam), test split = held-out wordings + held-out family. `finetune.py` = Unsloth
QLoRA on Qwen2.5-1.5B/0.5B (4-bit), loss on the response only, optional GGUF Q4_K_M export.
`evaluate.py` scores any OpenAI-compatible endpoint (JSON validity, tactic micro-F1, stage accuracy, AUC).
**Status: Partial — code only; no model has been trained (no GPU here), no config/hash records.**

## 8. Authentication and authorization (today)

- Single mechanism: `X-API-Key` header. Tester keys `ck_<40 hex>` issued by open signup; one admin key from
  `ADMIN_API_KEY` (default **`change-me-admin`** in config, `.env.example` and compose).
- `current_tester`: optional unless `REQUIRE_API_KEY=true`; the admin key is also accepted as a tester key.
- `require_admin`: admin key, or a tester whose `role` is `analyst`/`admin`. Used on two read routes only.
- No passwords, no Argon2id, no MFA, no sessions/cookies, no token expiry/rotation/revocation, no lockout,
  no email verification, no RBAC beyond three role strings, no per-resource (owner) checks, no step-up,
  no audit log.
- Keys are stored in plaintext in the DB and in the browser's `localStorage`.

## 9. Secrets and configuration

- `app/config.py` reads env vars: `CHAKRAVYUH_ENV`, `DATABASE_URL`, `CHAKRAVYUH_ARTIFACTS`, `CHAKRAVYUH_DATA`,
  `CORS_ORIGINS`, `REQUIRE_API_KEY`, `ADMIN_API_KEY`, `STORE_MESSAGE_TEXT`; `DB_WAIT_SECONDS`;
  `CHAKRAVYUH_LLM_BASE_URL/API_KEY/MODEL`.
- `.gitignore` excludes `.env` and `.env.*` (keeps `.env.example`). No real secrets are committed.
- Weak defaults committed: `ADMIN_API_KEY=change-me-admin` fallback; `POSTGRES_PASSWORD: chakravyuh` in
  `docker-compose.yml` (DB has no host port by default; opt-in `docker-compose.dbport.yml` binds 127.0.0.1 only).
- The app does not refuse to start in `production` with default secrets. No encryption keys exist.
- Render blueprint generates `ADMIN_API_KEY` and sets `STORE_MESSAGE_TEXT=false`.

## 10. Privacy controls that already exist

- `STORE_MESSAGE_TEXT=false`: message text is scored in memory and not written; derived tags are kept.
- `client_tags`: a client can send on-device tags instead of text.
- Alert wording comes only from vetted templates (no free-form generated advice).
- Public dataset export drops text, payee ids and genomes and hashes session ids.

## 11. Docker and deployment

- `docker-compose.yml`: `db` (postgres:16-alpine, `pg_isready` TCP healthcheck, no host port), `api`
  (python:3.12-slim, CPU torch with PyPI fallback, generates simulator data at build time, healthcheck,
  `${API_HOST_PORT:-8000}`), `web` (node build → nginx:1.27-alpine, `${WEB_HOST_PORT:-8080}`).
- Containers run as root; nginx has no security headers and no TLS (TLS expected from the host platform).
- `render.yaml`: managed Postgres + Docker API + static web. Not deployed publicly yet.
- `scripts/validate_docker.ps1` (PowerShell 5.1/7, any OS): build, health, smoke (14 checks), e2e checks,
  arena/adapt, persistence, privacy mode, pytest inside the container. Passed in CI and on the owner's laptop.

## 12. Tests and CI

- `backend/tests`: `test_api.py` (11), `test_sim.py` (11), `test_ml.py` (8), `test_db_startup.py` (2).
  Coverage: API flows, privacy mode, overlong inputs → 422, simulator determinism and behaviours, model
  training/inference, campaign detection, DB startup retry. **No security tests** (IDOR, authz, rate limits,
  CSRF, upload, pickle integrity) and **no real-data tests**.
- `.github/workflows/ci.yml`: backend (ruff + pytest), frontend (tsc + build), docker (full stack), validator
  (pwsh validator with a deliberate 5432/8000 port clash). Last run on `58438cb`: all passed.

## 13. Gaps against the new specification

| Workstream | Gap | Severity |
|---|---|---|
| A. Real data | No real datasets, manifests, licences, leakage audit, or separate real/synthetic evaluation tracks | High (claims) |
| A. Real data | Sandbox egress allows GitHub and PyPI only; Hugging Face, Zenodo, UCI, Mendeley, Kaggle, Figshare unreachable from the build environment | Environment |
| B. Agent UI | No node canvas, no live execution state, no event stream, no inspector | Feature |
| C. Security | Unauthenticated read of all sessions and message text (`GET /v1/sessions*`) | **High** |
| C. Security | Unauthenticated model change: `POST /v1/demo/arena/adapt` swaps the live model and can overwrite artifacts; `epochs` unbounded (DoS) | **High** |
| C. Security | No ownership checks on session events/close/alert responses (IDOR) | High |
| C. Security | Unauthenticated campaign refresh/approval | Medium |
| C. Security | Pickle model loading without hash verification | Medium |
| C. Security | Plaintext API keys in DB and `localStorage`; default admin key; no production guard | Medium |
| C. Security | No rate limiting, security headers, audit log, encryption at rest, MFA, RBAC | Medium |
| Sentinel | Untrained (needs a GPU, e.g. Colab/Kaggle notebook run by the owner) | Feature |
| Docs | README results section partly stale (older arena numbers) | Low |

## 14. What must be preserved

The simulator, attacker/victim/defender agents, evolution and co-evolution loop, the model stack, vetted
alert templates, privacy mode, Docker validation and CI must keep working. New work is added beside them:
real-data pipelines in new modules and directories, the agent canvas as new UI routes, and security as
middleware/dependencies applied to the existing routers.
