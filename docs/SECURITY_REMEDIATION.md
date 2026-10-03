# Security remediation (Phase 0.5)

Fixes for the access-control findings in `CHAKRAVYUH_CURRENT_ARCHITECTURE.md` §13, made before any
real-data work. Scope: authentication, authorization, resource ownership, sign-in sessions, model
integrity, rate limiting and audit logging. **Not in scope (and not claimed):** encryption at rest,
end-to-end encryption, MFA, email verification, password reset. Those come after the threat model.

No model was retrained and no simulator, agent, ScamSeq, tagger, payee graph, fusion, policy or
evolution code changed behaviour. The committed artifacts are byte-for-byte the same; only a
`manifest.json` of their SHA-256 digests was added. The regression checks give the same results as before
the change (Customs scam held at level 4 when UPI opens, genuine flat deposit at level 0).

## 1. Vulnerabilities fixed

| # | Finding (before) | Threat | Fix |
|---|---|---|---|
| V1 | `GET /v1/sessions` and `/v1/sessions/{id}` had no authentication and returned every session, including stored message text | Anyone could read every user's conversations and alerts | Sign-in required; list returns only the caller's sessions; a session that isn't yours returns the same 404 as one that doesn't exist |
| V2 | `POST /v1/demo/arena/adapt` had no authentication, replaced the live defender model, and with `persist=true` overwrote `scamseq.pt` / `policy.json` | Anyone could change or overwrite the production model | MODEL_ENGINEER role required; `persist=true` also needs `model:persist` **and** a password re-entry within the last 5 minutes |
| V3 | `epochs` on adapt was unbounded | One request could occupy the server for hours | Server-side bound `1 ≤ epochs ≤ 8` (422 otherwise), per-user rate limit, one model operation at a time |
| V4 | Adding events, closing sessions and answering alerts had no ownership check | Anyone could alter another person's session or mark a scam "legit" | Owner-only, enforced in the route; denial is audited |
| V5 | Campaign refresh and approve/reject had no authentication; campaign cards could quote any stored session's message and payee | Unauthenticated changes; cross-user leak of message text through public cards | `campaigns:manage` permission; user sessions are stripped of text and payee IDs before cards are built |
| V6 | Shared admin key with a known default `change-me-admin` | Default credential grants admin data | Admin key retired completely; ADMIN is an account role. A weak/default bootstrap password stops the API from starting |
| V7 | Beta sign-up let anyone pick `role: analyst`, which unlocked the tester list and all feedback | Self-service privilege escalation | Tester keys grant nothing except feedback attribution; admin data needs an ADMIN account |
| V8 | Tester keys stored in plaintext in the DB and in browser `localStorage` | Key theft from DB dumps or via XSS | Only SHA-256 stored; key shown once; nothing in browser storage |
| V9 | Pickled model files loaded without any check | Code execution via a swapped `.pkl`; silent corruption | SHA-256 manifest verified before any file is opened for loading; mismatch → refused, API runs rules-only and reports why |
| V10 | No rate limits, no security headers, no audit trail | Brute force, cost DoS, framing/sniffing, no accountability | See §6–§8 |

## 2. Authentication flow

```
register (email + password)  ──►  Argon2id hash stored (users.password_hash), role = ANALYST
login                        ──►  verify Argon2id (dummy hash for unknown emails: same timing, same error)
                             ──►  new 256-bit random token  ──►  Set-Cookie: chakravyuh_session=<token>;
                                                                 HttpOnly; SameSite=Lax; Secure (prod)
                             ──►  DB stores SHA-256(token) only (auth_sessions), absolute TTL 8 h, idle 2 h
                             ──►  body returns {user, csrf_token}; csrf_token = SHA-256("csrf:" + token)
every request                ──►  cookie → SHA-256 → auth_sessions row; reject if revoked / expired / idle /
                                  user disabled
POST / PATCH                 ──►  X-CSRF-Token must equal the derived token (constant-time compare)
reauth (password)            ──►  sets auth_sessions.reauth_at; valid 5 min for step-up actions
logout                       ──►  revoked_at set server-side; replaying the old cookie fails
role change / disable        ──►  all of that user's sessions revoked
```

- Passwords: Argon2id (argon2-cffi defaults: 64 MiB, 3 passes, 4 lanes), 12–128 characters, common and
  project-default values rejected; transparently re-hashed if parameters change.
- The browser never sees the session token (HttpOnly) and never stores anything: the frontend keeps the
  CSRF token in module memory and asks `/v1/auth/me` for it again after a reload.
- `COOKIE_SECURE=true` is the default in production and the API refuses to start in production without
  it. Local plain-HTTP development and the Docker stack set it to false explicitly.
- Signing in does **not** satisfy step-up; `reauth_at` is only set by `/v1/auth/reauth`.
- First admin: `BOOTSTRAP_ADMIN_EMAIL` + `BOOTSTRAP_ADMIN_PASSWORD` (both or neither), or
  `python -m app.manage create-user --role ADMIN` (password from a prompt or environment variable, never
  a command-line argument).

## 3. Authorization matrix

Roles: **VIEWER**, **ANALYST** (default for sign-ups), **MODEL_ENGINEER**, **ADMIN**. Only permissions that a
route checks exist (`app/security/rbac.py`). "Own" means the session's `owner_id` is the caller.

| Endpoint | Anonymous | VIEWER | ANALYST | MODEL_ENGINEER | ADMIN | Extra check |
|---|---|---|---|---|---|---|
| `GET /health`, `/v1/meta`, `/v1/metrics`, `/v1/campaigns`, `/v1/payees/{vpa}/risk`, demo scenarios | ✓ | ✓ | ✓ | ✓ | ✓ | rate limit on scoring paths |
| `POST /v1/score` (stateless, nothing stored) | ✓ | ✓ | ✓ | ✓ | ✓ | 60/min per client |
| `POST /v1/demo/simulate`, `POST /v1/demo/arena` (simulation only) | ✓ | ✓ | ✓ | ✓ | ✓ | rate limit; arena single-flight |
| `GET /v1/sessions`, `GET /v1/sessions/{id}` | 401 | own | own | own | own | `sessions:read` |
| `POST /v1/sessions`, `…/events`, `…/close`, `POST /v1/alerts/{id}/respond` | 401 | 403 | own | own | own | `sessions:write` + CSRF |
| `POST /v1/campaigns/refresh`, `PATCH /v1/campaigns/{id}` | 401 | 403 | ✓ | ✓ | ✓ | `campaigns:manage` + CSRF |
| `POST /v1/demo/arena/adapt` | 401 | 403 | 403 | ✓ | 403 | `model:adapt`, epochs ≤ 8 |
| `POST /v1/demo/arena/adapt?persist=true` | 401 | 403 | 403 | ✓ | 403 | `model:persist` + password ≤ 5 min |
| `GET /v1/admin/users`, `PATCH /v1/admin/users/{id}` | 401 | 403 | 403 | 403 | ✓ | `users:manage` + password ≤ 5 min; not on self |
| `GET /v1/admin/audit` | 401 | 403 | 403 | 403 | ✓ | `audit:read` |
| `GET /v1/beta/feedback`, `/v1/beta/testers` | 401 | 403 | 403 | 403 | ✓ | `beta:read` |
| `POST /v1/beta/signup`, `/v1/beta/feedback` | ✓ | ✓ | ✓ | ✓ | ✓ | rate limit; tester key only attributes feedback |

Separation of duties: ADMIN cannot change models, and MODEL_ENGINEER cannot manage users or read the
audit log. An admin who needs model access grants MODEL_ENGINEER to an account. That role change is
itself step-up protected and audited. No role can read another user's sessions.

## 4. Session isolation

- `sessions.owner_id` is set from the signed-in user at creation and checked on every read and write
  (`_owned()` in `routers/sessions.py`). Alerts are checked through their session.
- Not yours → `404 Session not found` / `404 Alert not found`, identical to a missing ID, so IDs can't be
  probed. The attempt is recorded as `AUTHORIZATION_DENIED`.
- Sessions created before this change have no owner and are returned to nobody. Existing databases get
  the `owner_id` column added on startup; this was tested on a PostgreSQL database created by the
  previous release.

## 5. Model protection and integrity

```
save (train.py / Engine.save, arena adapt persist, coevolve --persist)
  → write file (adapt uses temp file + atomic rename)
  → register SHA-256 + size in artifacts/manifest.json (atomic rename)
load (API start)
  → every artifact present must be in the manifest and match its SHA-256
  → only then: pickle.load / torch.load(weights_only=True)
  → any mismatch, missing entry or missing manifest: IntegrityError → API does NOT load the files,
    runs rules-only, reports `integrity_error` in /health, writes MODEL_LOAD_FAILURE to the audit log
```

`ArtifactVerifier` (in `chakravyuh/ml/integrity.py`) is the interface where a signed-manifest verifier can
be added later. No signing is implemented, and nothing here claims signatures.

Limitation: the manifest sits next to the artifacts. This check catches corruption, partial writes, and
files swapped in outside a registered save. It does **not** stop an attacker who can already write to
the artifacts directory, because they can rewrite the manifest too. Closing that gap needs signatures
from a key held off the server.

## 6. Rate limits

Sliding-window, in-process (`app/security/ratelimit.py`). 429 with `Retry-After` when exceeded.

| Limit | Scope | Max | Window |
|---|---|---|---|
| Sign-up | client address | 5 | 1 h |
| Sign-in | client address | 10 | 5 min |
| Sign-in | account email | 5 | 5 min |
| Re-authentication | user | 5 | 5 min |
| Create session | user | 30 | 1 min |
| Add event (scoring) | user | 120 | 1 min |
| Stateless score, scenario scoring | client address | 60 | 1 min |
| Simulate | client address | 10 | 1 min |
| Arena (attacker evolution) | client address | 6 | 10 min |
| Defender adapt | user | 3 | 10 min |
| Campaign refresh | user | 6 | 10 min |
| Admin user operations | user | 30 | 10 min |
| Beta sign-up / feedback | client address | 5 / 20 | 1 h / 10 min |

Arena runs and defender updates also share a single-flight lock, so a second one gets 429 instead of
queueing. Client address = TCP peer, or the last `X-Forwarded-For` hop when `TRUST_FORWARDED_FOR=true`
(set for nginx in Docker and Render's proxy).

**Epoch bound:** `MAX_ADAPT_EPOCHS = 8` (`app/config.py`). The co-evolution CLI default is 4 epochs.
Measured here, on 4 vCPUs with 5,920 replay sessions, one adapt takes about 8 s of fixed evaluation plus
about 1–1.5 s per epoch: 1 epoch ≈ 10 s, 3 ≈ 12 s, 8 ≈ 17 s. So the worst allowed request stays under
about 20 s here, and a few times that on a slow laptop.

## 7. Security headers

API (all responses): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin`,
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (not on `/docs`, which loads
Swagger UI from a CDN), `Cache-Control: no-store` on `/v1/*`, `X-Request-ID`, and HSTS when cookies are
Secure. CORS is restricted to the configured origins, methods `GET/POST/PATCH/OPTIONS` and the headers
the frontend actually sends.

Web (nginx, and Render static headers): a CSP that allows only same-origin scripts, plus Google Fonts for
styles and fonts, and `frame-ancestors 'none'`, along with nosniff, DENY, referrer and permissions
policies. I checked the built app in Chromium with this CSP: sign-up, sign-in, a live session and the
Arena page all worked, with no CSP violations in the console.

## 8. Audit log

Table `audit_events`: time, request ID, action, result (success / denied / failure), actor ID and role,
resource type and ID, reason, source address, and a filtered detail object. Writes use their own
transaction, so denials are recorded even though the request fails. ADMIN reads it at
`GET /v1/admin/audit`.

Actions: `LOGIN`, `FAILED_LOGIN`, `LOGOUT`, `REGISTER`, `REAUTH`, `FAILED_REAUTH`, `SESSION_CREATE`,
`SESSION_ACCESS`, `SESSION_MUTATION`, `MODEL_ADAPT`, `MODEL_PERSIST`, `MODEL_LOAD_FAILURE`,
`AUTHORIZATION_DENIED`, `ADMIN_ACTION`, `ROLE_CHANGE`, `CAMPAIGN_CHANGE`.

Never logged: passwords, session or CSRF tokens, API keys, cookies, message text. Detail keys matching
password/token/secret/key/cookie/auth/csrf/text/message/comment/credential are dropped whatever the
caller passes. A test scans every audit row for the real password, token, CSRF token and message text.

## 9. Tests

`backend/tests/test_security.py` (runs on SQLite and PostgreSQL 16, and inside the API image):

| # | Requirement | Test |
|---|---|---|
| 1 | Anonymous user cannot read sessions | `test_01_…` (401 on list, read, create, add event, close, respond) |
| 2–5 | User A cannot read / add events / close / answer alerts of user B | `test_02_to_05_…` (404s, B's data unchanged, denials audited) |
| 6 | Unauthorized user cannot trigger adaptation | `test_06_…` (anonymous 401; VIEWER, ANALYST, ADMIN 403; MODEL_ENGINEER 200) |
| 7 | Unauthorized user cannot persist | `test_07_…` (ANALYST 403; engineer without step-up 403 and file unchanged; wrong password 401; after reauth persists and the new files load) |
| 8 | Excessive epochs rejected | `test_08_…` (0, −1, 9, 1000, 10⁹ → 422) |
| 9 | Invalid authentication fails safely | `test_09_…` (same 401 for wrong password and unknown email, forged cookie, missing/forged CSRF, replay after logout, expired, disabled) |
| 10 | Passwords never stored in plaintext | `test_10_…` (Argon2id hash, tester key and session token stored as SHA-256 only) |
| 11 | Credentials not in localStorage | `test_11_…` (no browser storage anywhere in `frontend/src`; cookie HttpOnly + SameSite; token never in a response body) |
| 12 | Tampered artifact rejected | `test_12_…` (flipped byte, unregistered file, missing manifest; API stays rules-only and audits) |
| 13 | Security events audited | `test_13_…` (event set present, request ID and address recorded, no secrets in any row) |
| 14 | Rate limits work | `test_14_…` (sign-in per account and per address, adapt 3/10 min, arena 6/10 min, single-flight) |
| 15 | `change-me-admin` unusable | `test_15_…` (401 on every admin route; tester key grants nothing; weak bootstrap password stops startup) |
| – | Extra | weak passwords refused at sign-up; VIEWER can't create; admin role change needs step-up and is audited; headers present; campaign cards never quote user text or payees |

The smoke test went from 14 to 16 checks: sessions are refused without sign-in, and an account can be
created and signed in. The CI Docker job also checks that anonymous adapt (including `epochs=1000`) and
the old admin key both get 401.

## 10. Remaining risks

| Risk | Status |
|---|---|
| No MFA, email verification or password reset | Planned (spec Phase 7). Password-only step-up for now. |
| Rate limits are per process and reset on restart | Fine for the single-worker deployments here; needs a shared store (Redis) before scaling out. |
| With `TRUST_FORWARDED_FOR=true` and the API port also published (local Docker), a client that goes straight to the API can fake its address and dodge per-address limits | Per-user and per-account limits still apply. In production, publish only the proxy. |
| Artifact manifest is not signed | Anyone who can write to the artifacts directory can rewrite the manifest. Signing is planned. |
| Pickle is still the format for the tagger and fusion models | Mitigated by verifying the digest before loading; moving to a non-executable format is better. |
| No encryption at rest; message text is stored unless `STORE_MESSAGE_TEXT=false` | Encryption is a separate phase after the threat model. Production config keeps text off. |
| Public endpoints: stateless scoring, payee risk lookup and demo can be used as an oracle to tune scams | Rate-limited; threshold jitter and authenticated scoring for partners are planned. |
| The arena's attacker population is global: an anonymous arena run changes what the next adapt learns from | Only simulator-generated data, and acceptance is still champion/challenger. Per-user arena state is planned. |
| Default Render URLs are different sites, so cookies need `SameSite=None`; browsers that block third-party cookies (Safari) will not keep the sign-in | Use a custom domain with the web app and API on the same site, then `COOKIE_SAMESITE=lax`. |
| Sign-up says when an email is already registered (409) | Accepted for the beta; invite-only mode is `ALLOW_REGISTRATION=false`. |
| Audit log lives in the same database, isn't tamper-evident, and has no retention policy (it stores source addresses) | Append-only storage, hash chaining and retention are planned. |
| Containers run as root; PostgreSQL password in `docker-compose.yml` is a local default (no host port) | Hardening of the images is planned; production uses the platform's database credentials. |
| `/docs` is public | Fine for the beta; restrict in production if needed. |
| Pre-existing sessions have no owner; old tester keys stopped working (stored in plaintext before) | Intentional. |
