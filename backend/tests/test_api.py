import os

os.environ["DATABASE_URL"] = "sqlite:///./test_chakravyuh.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    if os.path.exists("test_chakravyuh.db"):
        os.remove("test_chakravyuh.db")
    with TestClient(app) as c:
        yield c
    os.remove("test_chakravyuh.db")


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok"


def test_scam_scenario_alerts_before_payment(client):
    sc = client.get("/v1/demo/scenarios/investment_group").json()
    first_alert = next(i for i, s in enumerate(sc["scores"]) if s["escalated"])
    first_pay = next(i for i, e in enumerate(sc["events"]) if e["type"] == "PAY" and e["attrs"]["amount_ratio"] > 1.5)
    assert first_alert < first_pay


@pytest.mark.parametrize("key", ["big_purchase", "new_number_family"])
def test_legit_lookalikes_stay_quiet(client, key):
    sc = client.get(f"/v1/demo/scenarios/{key}").json()
    assert max(s["level"] for s in sc["scores"]) == 0


def test_unseen_family_detected(client):
    sc = client.get("/v1/demo/scenarios/echallan_link").json()
    assert max(s["level"] for s in sc["scores"]) >= 1


def test_live_session_flow(client):
    s = client.post("/v1/sessions", json={"language": "en", "channel": "sms"}).json()
    sid = s["id"]
    events = [
        {"type": "MSG_RECV", "text": "This is CBI. A parcel in your name contains illegal items. Stay on the line."},
        {"type": "CALL", "attrs": {"known": False, "minutes": 90}},
        {"type": "MSG_RECV", "text": "You are under digital arrest. Do not tell anyone, including family."},
        {"type": "MSG_RECV", "text": "Transfer Rs 4,00,000 to RBI verification account acc01234@ybl now."},
        {"type": "UPI_OPEN"},
        {"type": "PAYEE_NEW", "attrs": {"payee": "acc01234@ybl", "payee_age_days": 4}},
    ]
    last = None
    for i, e in enumerate(events):
        last = client.post(f"/v1/sessions/{sid}/events", json={**e, "t": i * 120}).json()
    assert last["latest"]["level"] >= 2
    detail = client.get(f"/v1/sessions/{sid}").json()
    assert detail["alerts"], "expected at least one alert"
    aid = detail["alerts"][0]["id"]
    assert client.post(f"/v1/alerts/{aid}/respond", json={"response": "cancelled"}).json()["response"] == "cancelled"


def test_privacy_mode_client_tags(client):
    r = client.post("/v1/score", json={"language": "en", "events": [
        {"type": "MSG_RECV", "client_tags": {"tactics": ["authority", "fear", "urgency"], "p_scam": 0.95}},
        {"type": "CALL", "attrs": {"known": False, "minutes": 60}},
        {"type": "MSG_RECV", "client_tags": {"tactics": ["payment_request", "authority"], "p_scam": 0.97}},
        {"type": "UPI_OPEN"},
    ]}).json()
    assert r["latest"]["p"] > 0.5


def test_beta_signup_and_feedback(client):
    r = client.post("/v1/beta/signup", json={"email": "alpha@example.com", "name": "Alpha"}).json()
    key = r["api_key"]
    assert key.startswith("ck_")
    f = client.post("/v1/beta/feedback", json={"kind": "false_alert", "rating": 4, "comment": "ok"},
                    headers={"X-API-Key": key})
    assert f.status_code == 201
    assert client.get("/v1/beta/testers").status_code == 403


def test_metrics_and_meta(client):
    assert "sessions" in client.get("/v1/metrics").json()
    assert client.get("/v1/meta").json()["model"]["loaded"] is True
