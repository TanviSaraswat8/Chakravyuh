"""Security tests: authentication, session isolation, model protection, integrity, rate limits, audit.

Numbers in the test names match the checklist in docs/SECURITY_REMEDIATION.md.
"""

import hashlib
import json
import os
import re
import shutil
from datetime import timedelta
from pathlib import Path

SQLITE_FILE = "test_chakravyuh.db"     # same file as test_api.py: the engine is created once per run
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///./{SQLITE_FILE}")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import MAX_ADAPT_EPOCHS, settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditEvent, AuthSession, BetaTester, Event, ScamSession, User  # noqa: E402
from tests.helpers import PASSWORD, make_user, sign_in  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SCAM = [
    {"type": "MSG_RECV", "text": "This is CBI. A parcel in your name contains illegal items. Stay on the line."},
    {"type": "CALL", "attrs": {"known": False, "minutes": 90}},
    {"type": "MSG_RECV", "text": "You are under digital arrest. Do not tell anyone. Transfer Rs 4,00,000 now."},
    {"type": "SCREEN_SHARE"},
    {"type": "UPI_OPEN"},
]


@pytest.fixture(scope="module")
def app_ready():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:          # runs startup: tables, model load
        yield c
    Base.metadata.drop_all(engine)
    engine.dispose()
    if os.path.exists(SQLITE_FILE):
        os.remove(SQLITE_FILE)


def new_client(app_ready) -> TestClient:
    return TestClient(app)


def audit_rows(action: str | None = None) -> list[AuditEvent]:
    with SessionLocal() as db:
        q = select(AuditEvent).order_by(AuditEvent.id)
        if action:
            q = q.where(AuditEvent.action == action)
        return list(db.scalars(q).all())


def scam_session(c: TestClient) -> tuple[str, str]:
    sid = c.post("/v1/sessions", json={"language": "en", "channel": "sms"}).json()["id"]
    for i, e in enumerate(SCAM):
        assert c.post(f"/v1/sessions/{sid}/events", json={**e, "t": i * 120}).status_code == 200
    alerts = c.get(f"/v1/sessions/{sid}").json()["alerts"]
    assert alerts, "scam session should raise an alert"
    return sid, alerts[0]["id"]


# 1 ------------------------------------------------------------------------------------------------
def test_01_anonymous_cannot_read_or_change_sessions(app_ready):
    owner = new_client(app_ready)
    sign_in(owner)
    sid, aid = scam_session(owner)
    anon = new_client(app_ready)
    assert anon.get("/v1/sessions").status_code == 401
    assert anon.get(f"/v1/sessions/{sid}").status_code == 401
    assert anon.post("/v1/sessions", json={}).status_code == 401
    assert anon.post(f"/v1/sessions/{sid}/events", json={"type": "UPI_OPEN"}).status_code == 401
    assert anon.post(f"/v1/sessions/{sid}/close").status_code == 401
    assert anon.post(f"/v1/alerts/{aid}/respond", json={"response": "legit"}).status_code == 401


# 2-5 ----------------------------------------------------------------------------------------------
def test_02_to_05_user_a_cannot_touch_user_b_session(app_ready):
    a, b = new_client(app_ready), new_client(app_ready)
    sign_in(a)
    user_b = sign_in(b)
    sid, aid = scam_session(b)
    n_events = len(b.get(f"/v1/sessions/{sid}").json()["events"])
    denied_before = len(audit_rows("AUTHORIZATION_DENIED"))

    # 2: read. Same answer as a session that doesn't exist, so IDs can't be probed.
    r = a.get(f"/v1/sessions/{sid}")
    assert r.status_code == 404 and r.json()["detail"] == "Session not found"
    assert a.get("/v1/sessions/ffffffffffffffff").json()["detail"] == "Session not found"
    assert sid not in [s["id"] for s in a.get("/v1/sessions").json()]
    # 3: add events
    assert a.post(f"/v1/sessions/{sid}/events", json={"type": "PAY", "attrs": {"amount": 1}}).status_code == 404
    # 4: close
    assert a.post(f"/v1/sessions/{sid}/close").status_code == 404
    # 5: answer alert
    r = a.post(f"/v1/alerts/{aid}/respond", json={"response": "legit"})
    assert r.status_code == 404 and r.json()["detail"] == "Alert not found"

    after = b.get(f"/v1/sessions/{sid}").json()
    assert len(after["events"]) == n_events and after["status"] == "open"
    assert all(al["response"] is None for al in after["alerts"])
    with SessionLocal() as db:
        assert db.get(ScamSession, sid).owner_id == user_b.id
    assert len(audit_rows("AUTHORIZATION_DENIED")) >= denied_before + 4


def test_viewer_can_read_but_not_create(app_ready):
    v = new_client(app_ready)
    sign_in(v, "VIEWER")
    assert v.get("/v1/sessions").status_code == 200
    assert v.post("/v1/sessions", json={}).status_code == 403


# 6-8 ----------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def attackers(app_ready):
    """A small attacker population so the defender has something to learn from."""
    r = new_client(app_ready).post("/v1/demo/arena", json={"generations": 1, "population": 4,
                                                           "per_genome": 1, "fresh": True})
    assert r.status_code == 200


def test_06_only_model_engineers_can_adapt(app_ready, attackers):
    assert new_client(app_ready).post("/v1/demo/arena/adapt?epochs=1").status_code == 401
    for role in ("VIEWER", "ANALYST", "ADMIN"):
        c = new_client(app_ready)
        sign_in(c, role)
        assert c.post("/v1/demo/arena/adapt?epochs=1").status_code == 403, role
    eng = new_client(app_ready)
    sign_in(eng, "MODEL_ENGINEER")
    r = eng.post("/v1/demo/arena/adapt?epochs=1")
    assert r.status_code == 200 and "detection_after" in r.json() and r.json()["persisted"] is False
    assert audit_rows("MODEL_ADAPT")


def test_07_persist_needs_role_and_fresh_password(app_ready, attackers, tmp_path, monkeypatch):
    analyst = new_client(app_ready)
    sign_in(analyst)
    assert analyst.post("/v1/demo/arena/adapt?epochs=1&persist=true").status_code == 403

    art = tmp_path / "artifacts"
    shutil.copytree(settings.artifacts_dir, art)
    object.__setattr__(settings, "artifacts_dir", str(art))
    original = Path(art / "scamseq.pt").read_bytes()
    try:
        eng = new_client(app_ready)
        sign_in(eng, "MODEL_ENGINEER")
        r = eng.post("/v1/demo/arena/adapt?epochs=1&persist=true")       # signed in, but no step-up
        assert r.status_code == 403 and r.headers.get("X-Step-Up-Required") == "true"
        assert Path(art / "scamseq.pt").read_bytes() == original
        assert eng.post("/v1/auth/reauth", json={"password": "wrong password here"}).status_code == 401
        assert eng.post("/v1/auth/reauth", json={"password": PASSWORD}).status_code == 200
        r = eng.post("/v1/demo/arena/adapt?epochs=1&persist=true")
        assert r.status_code == 200, r.text
        assert audit_rows("MODEL_PERSIST")
        if r.json()["persisted"]:
            from chakravyuh.ml.engine import Engine
            Engine.load(art)                 # new files were registered in the manifest
    finally:
        object.__setattr__(settings, "artifacts_dir", str(REPO / "backend" / "artifacts"))


@pytest.mark.parametrize("epochs", [0, -1, MAX_ADAPT_EPOCHS + 1, 1000, 10**9])
def test_08_excessive_epochs_rejected(app_ready, epochs):
    c = new_client(app_ready)
    sign_in(c, "MODEL_ENGINEER")
    r = c.post(f"/v1/demo/arena/adapt?epochs={epochs}")
    assert r.status_code == 422


# 9 ------------------------------------------------------------------------------------------------
def test_09_invalid_authentication_fails_safely(app_ready):
    u = make_user()
    c = new_client(app_ready)
    wrong = c.post("/v1/auth/login", json={"email": u.email, "password": "not the password!"})
    unknown = c.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password"}
    assert "set-cookie" not in wrong.headers

    c.cookies.set("chakravyuh_session", "forged-token-value")
    assert c.get("/v1/sessions").status_code == 401
    assert c.get("/v1/auth/me").status_code == 401

    # valid cookie but no CSRF token on a state-changing request
    d = new_client(app_ready)
    sign_in(d)
    del d.headers["X-CSRF-Token"]
    assert d.post("/v1/sessions", json={}).status_code == 403
    d.headers["X-CSRF-Token"] = "0" * 64
    assert d.post("/v1/sessions", json={}).status_code == 403

    # logout revokes the session server-side, even if the old cookie is replayed
    e = new_client(app_ready)
    sign_in(e)
    token = e.cookies.get("chakravyuh_session")
    assert e.post("/v1/auth/logout").status_code == 200
    replay = new_client(app_ready)
    replay.cookies.set("chakravyuh_session", token)
    assert replay.get("/v1/sessions").status_code == 401

    # expired and disabled
    f = new_client(app_ready)
    user_f = sign_in(f)
    with SessionLocal() as db:
        s = db.scalar(select(AuthSession).where(AuthSession.user_id == user_f.id))
        s.expires_at = s.created_at - timedelta(seconds=1)
        db.commit()
    assert f.get("/v1/sessions").status_code == 401
    g = new_client(app_ready)
    user_g = sign_in(g)
    with SessionLocal() as db:
        db.get(User, user_g.id).status = "disabled"
        db.commit()
    assert g.get("/v1/sessions").status_code == 401
    assert g.post("/v1/auth/login", json={"email": user_g.email, "password": PASSWORD}).status_code == 401


def test_weak_passwords_rejected_at_signup(app_ready):
    c = new_client(app_ready)
    for pw in ("short", "change-me-admin", "password123"):
        assert c.post("/v1/auth/register", json={"email": "weak@example.com", "password": pw}).status_code == 400
    r = c.post("/v1/auth/register", json={"email": "ok@example.com", "password": PASSWORD})
    assert r.status_code == 201 and r.json()["role"] == "ANALYST"
    assert c.post("/v1/auth/register", json={"email": "ok@example.com", "password": PASSWORD}).status_code == 409


# 10 -----------------------------------------------------------------------------------------------
def test_10_passwords_and_keys_never_stored_plaintext(app_ready):
    u = make_user(password="a distinct passphrase 42")
    with SessionLocal() as db:
        row = db.get(User, u.id)
        assert row.password_hash.startswith("$argon2id$")
        assert "a distinct passphrase 42" not in json.dumps({c.name: str(getattr(row, c.key, ""))
                                                              for c in User.__table__.columns})
    c = new_client(app_ready)
    key = c.post("/v1/beta/signup", json={"email": "keyed@example.com", "name": "K"}).json()["api_key"]
    with SessionLocal() as db:
        t = db.scalar(select(BetaTester).where(BetaTester.email == "keyed@example.com"))
        assert t.api_key_hash != key and t.api_key_hash == hashlib.sha256(key.encode()).hexdigest()
        tokens = [s.token_hash for s in db.scalars(select(AuthSession)).all()]
    sign_in(c)
    assert c.cookies.get("chakravyuh_session") not in tokens


# 11 -----------------------------------------------------------------------------------------------
def test_11_credentials_not_in_browser_storage(app_ready):
    src = REPO / "frontend" / "src"
    if not src.is_dir():
        pytest.skip("frontend source not present (API image); this check runs in the repository and CI")
    offenders = [str(p.relative_to(REPO)) for p in src.rglob("*.ts*")
                 if re.search(r"localStorage|sessionStorage|indexedDB", p.read_text(encoding="utf-8"))]
    assert offenders == [], f"browser storage used in {offenders}"
    # The session token is only ever in an HttpOnly cookie, never in a response body.
    u = make_user()
    c = new_client(app_ready)
    r = c.post("/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert c.cookies.get("chakravyuh_session") not in r.text
    assert c.cookies.get("chakravyuh_session") not in c.get("/v1/auth/me").text


# 12 -----------------------------------------------------------------------------------------------
def test_12_tampered_model_artifact_rejected(app_ready, tmp_path):
    from app.services import scoring
    from chakravyuh.ml.engine import Engine
    from chakravyuh.ml.integrity import MANIFEST, IntegrityError

    good = tmp_path / "good"
    shutil.copytree(settings.artifacts_dir, good)
    Engine.load(good)

    bad = tmp_path / "bad"
    shutil.copytree(good, bad)
    blob = bytearray((bad / "tagger.pkl").read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    (bad / "tagger.pkl").write_bytes(bytes(blob))
    with pytest.raises(IntegrityError, match="tagger.pkl"):
        Engine.load(bad)

    unregistered = tmp_path / "unregistered"
    shutil.copytree(good, unregistered)
    m = json.loads((unregistered / MANIFEST).read_text())
    del m["files"]["fusion.pkl"]
    (unregistered / MANIFEST).write_text(json.dumps(m))
    with pytest.raises(IntegrityError, match="not registered"):
        Engine.load(unregistered)

    nomanifest = tmp_path / "nomanifest"
    shutil.copytree(good, nomanifest)
    (nomanifest / MANIFEST).unlink()
    with pytest.raises(IntegrityError):
        Engine.load(nomanifest)

    # The API refuses too: it stays in rules-only mode, says why, and audits the failure.
    object.__setattr__(settings, "artifacts_dir", str(bad))
    scoring.get_engine.cache_clear()
    try:
        assert scoring.get_engine() is None
        status = scoring.model_status()
        assert status["loaded"] is False and "tagger.pkl" in status["integrity_error"]
        assert audit_rows("MODEL_LOAD_FAILURE")
    finally:
        object.__setattr__(settings, "artifacts_dir", str(REPO / "backend" / "artifacts"))
        scoring._LOAD_ERROR.clear()
        scoring.get_engine.cache_clear()
        assert scoring.get_engine() is not None


# 13 -----------------------------------------------------------------------------------------------
def test_13_security_events_are_audited_without_secrets(app_ready):
    c = new_client(app_ready)
    u = make_user(password="audit me please 123")
    c.post("/v1/auth/login", json={"email": u.email, "password": "wrong password 123"})
    r = c.post("/v1/auth/login", json={"email": u.email, "password": "audit me please 123"})
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    token = c.cookies.get("chakravyuh_session")
    sid = c.post("/v1/sessions", json={}).json()["id"]
    c.post(f"/v1/sessions/{sid}/events", json={"type": "MSG_RECV", "text": "SECRET-MESSAGE-TEXT-XYZ please pay"})
    c.get(f"/v1/sessions/{sid}")
    c.post("/v1/demo/arena/adapt?epochs=1")          # ANALYST: denied
    c.post("/v1/auth/logout")

    mine = [e for e in audit_rows() if e.actor_id == u.id]
    actions = {e.action for e in mine}
    assert {"FAILED_LOGIN", "LOGIN", "SESSION_CREATE", "SESSION_MUTATION", "SESSION_ACCESS",
            "AUTHORIZATION_DENIED", "LOGOUT"} <= actions
    assert all(e.request_id and e.source_ip for e in mine)
    with SessionLocal() as db:
        dump = json.dumps([[str(v) for v in (e.reason, e.detail, e.resource_id)]
                           for e in db.scalars(select(AuditEvent)).all()])
        stored_text = [e.text for e in db.scalars(select(Event).where(Event.session_id == sid)).all()]
    for secret in ("audit me please 123", "wrong password 123", token, r.json()["csrf_token"],
                   "SECRET-MESSAGE-TEXT-XYZ"):
        assert secret not in dump
    assert stored_text  # the message itself is stored on the session (STORE_MESSAGE_TEXT), not in the audit log


def test_admin_role_change_needs_step_up_and_is_audited(app_ready):
    admin = new_client(app_ready)
    sign_in(admin, "ADMIN")
    target = make_user("VIEWER")
    r = admin.patch(f"/v1/admin/users/{target.id}", json={"role": "ANALYST"})
    assert r.status_code == 403 and r.headers.get("X-Step-Up-Required") == "true"
    assert admin.post("/v1/auth/reauth", json={"password": PASSWORD}).status_code == 200
    assert admin.patch(f"/v1/admin/users/{target.id}", json={"role": "ANALYST"}).json()["role"] == "ANALYST"
    assert any(e.resource_id == target.id for e in audit_rows("ROLE_CHANGE"))
    analyst = new_client(app_ready)
    sign_in(analyst)
    assert analyst.get("/v1/admin/users").status_code == 403
    assert analyst.get("/v1/admin/audit").status_code == 403
    assert admin.get("/v1/admin/audit?limit=5").status_code == 200


# 14 -----------------------------------------------------------------------------------------------
def test_14_rate_limits_on_expensive_and_sensitive_endpoints(app_ready, monkeypatch):
    from app.routers import demo as demo_router
    from app.security import ratelimit

    c = new_client(app_ready)
    u = make_user()
    codes = [c.post("/v1/auth/login", json={"email": u.email, "password": "wrong password!!"}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429                       # per account
    ratelimit.limiter.reset()
    codes = [c.post("/v1/auth/login", json={"email": f"x{i}@example.com", "password": "wrong password!!"}).status_code
             for i in range(11)]
    assert codes[-1] == 429 and "Retry-After" in c.post("/v1/auth/login", json={
        "email": "y@example.com", "password": "wrong password!!"}).headers   # per client address

    # Model adaptation: 3 per 10 minutes per engineer (stubbed so the test measures the limiter only).
    monkeypatch.setattr(demo_router, "adapt", lambda epochs, persist: {"accepted": False, "persisted": False})
    ratelimit.limiter.reset()                 # this client address is still locked out from above
    eng = new_client(app_ready)
    sign_in(eng, "MODEL_ENGINEER")
    assert [eng.post("/v1/demo/arena/adapt?epochs=1").status_code for _ in range(4)] == [200, 200, 200, 429]

    # The public arena: 6 per 10 minutes per client, and never two model operations at once.
    monkeypatch.setattr(demo_router, "arena", lambda *a, **k: {"history": []})
    body = {"generations": 1, "population": 4, "per_genome": 1}
    with ratelimit.model_ops:
        assert c.post("/v1/demo/arena", json=body).status_code == 429
    assert [c.post("/v1/demo/arena", json=body).status_code for _ in range(6)] == [200] * 5 + [429]


# 15 -----------------------------------------------------------------------------------------------
def test_15_default_admin_key_is_not_usable(app_ready):
    c = new_client(app_ready)
    for path in ("/v1/beta/testers", "/v1/beta/feedback", "/v1/admin/users", "/v1/admin/audit"):
        assert c.get(path, headers={"X-API-Key": "change-me-admin"}).status_code == 401, path
    # A tester key never grants admin or session access either.
    key = c.post("/v1/beta/signup", json={"email": "t15@example.com", "name": "T"}).json()["api_key"]
    assert c.get("/v1/beta/testers", headers={"X-API-Key": key}).status_code == 401
    assert c.get("/v1/sessions", headers={"X-API-Key": key}).status_code == 401

    # A known-weak bootstrap admin password stops startup instead of being used.
    from app.services.users import bootstrap_admin
    object.__setattr__(settings, "bootstrap_admin_email", "boot@example.com")
    object.__setattr__(settings, "bootstrap_admin_password", "change-me-admin")
    try:
        with SessionLocal() as db, pytest.raises(RuntimeError, match="BOOTSTRAP_ADMIN_PASSWORD"):
            bootstrap_admin(db)
    finally:
        object.__setattr__(settings, "bootstrap_admin_email", "")
        object.__setattr__(settings, "bootstrap_admin_password", "")
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "boot@example.com")) is None


# Headers and campaign privacy -----------------------------------------------------------------------
def test_security_headers_present(app_ready):
    r = new_client(app_ready).get("/health")
    for h in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy",
              "X-Request-ID"):
        assert h in r.headers, h
    assert new_client(app_ready).get("/v1/meta").headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" not in new_client(app_ready).get("/docs").headers   # Swagger UI still works


def test_campaign_actions_need_analyst_and_cards_never_quote_users(app_ready):
    anon = new_client(app_ready)
    assert anon.post("/v1/campaigns/refresh").status_code == 401
    v = new_client(app_ready)
    sign_in(v, "VIEWER")
    assert v.post("/v1/campaigns/refresh").status_code == 403
    a = new_client(app_ready)
    sign_in(a)
    sid = a.post("/v1/sessions", json={}).json()["id"]
    for i, e in enumerate([{"type": "MSG_RECV", "text": "PRIVATE-CANARY-7731 send otp to claim refund"},
                           {"type": "LINK_OPEN"}, {"type": "UPI_OPEN"},
                           {"type": "PAY", "attrs": {"amount": 5000, "amount_ratio": 9, "payee": "canary7731@ybl"}}]):
        a.post(f"/v1/sessions/{sid}/events", json={**e, "t": i * 60})
    assert a.post("/v1/campaigns/refresh").status_code == 200
    public = anon.get("/v1/campaigns").text
    assert "PRIVATE-CANARY-7731" not in public and "canary7731@ybl" not in public
