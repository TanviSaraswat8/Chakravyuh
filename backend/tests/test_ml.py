"""Model tests: features never leak labels, calibration and conformal gates behave, the alert
ladder respects its limits, and the trained engine scores scams above legitimate sessions."""

import numpy as np
import pytest

from chakravyuh.ml.campaigns import CampaignDetector
from chakravyuh.ml.engine import Engine
from chakravyuh.ml.features import ATTR_NAMES, N_ATTRS, encode_session, pad_batch
from chakravyuh.ml.fusion import Fusion, ece
from chakravyuh.ml.policy import LinUCBPolicy, context
from chakravyuh.sim.agents import Genome
from chakravyuh.sim.simulator import Chakravyuh
from chakravyuh.sim.taxonomy import BENIGN_FAMILIES, SCAM_FAMILIES


@pytest.fixture(scope="module")
def engine():
    return Engine.load("artifacts")


@pytest.fixture(scope="module")
def sessions():
    sim = Chakravyuh(seed=21)
    scams = [sim.play(Genome(family=f), pool="test") for f in SCAM_FAMILIES for _ in range(3)]
    legit = [sim.play(Genome(family=f), pool="test") for f in BENIGN_FAMILIES for _ in range(3)]
    return scams, legit


def test_features_do_not_read_labels(sessions):
    scams, _ = sessions
    s = dict(scams[0])
    a = encode_session({**s, "label": 1}, {})
    b = encode_session({**s, "label": 0}, {})
    assert np.array_equal(a["attrs"], b["attrs"]) and np.array_equal(a["types"], b["types"])
    assert a["attrs"].shape[1] == N_ATTRS == len(ATTR_NAMES)
    assert not any("stage" in n or "label" in n for n in ATTR_NAMES)


def test_padding_masks(sessions):
    scams, legit = sessions
    batch = pad_batch([encode_session(scams[0], {}), encode_session(legit[0], {})])
    assert batch["mask"].sum() == len(scams[0]["events"][-48:]) + len(legit[0]["events"][-48:])


def test_conformal_threshold_caps_false_alarms():
    rng = np.random.default_rng(0)
    n = 4000
    y = (rng.random(n) < 0.4).astype(int)
    X = np.c_[rng.normal(y * 2.0, 1.0), rng.normal(0, 1, n), np.zeros((n, 7))]
    f = Fusion().fit(X[:2000], y[:2000], X[2000:3000], y[2000:3000])
    p = f.predict(X[3000:])
    legit = p[y[3000:] == 0]
    for eps in ("0.01", "0.05", "0.1"):
        far = (legit > f.thresholds[eps]).mean()
        assert far <= float(eps) + 0.03, (eps, far)
    assert ece(p, y[3000:]) < 0.1


def test_policy_never_holds_without_a_pending_payment():
    pol = LinUCBPolicy()
    pol.level_gates = [0, 0.1, 0.1, 0.1, 0.1]
    pol.min_p_for_hold = 0.1
    pol.b = [np.ones(8) * (10 * a) for a in range(5)]  # higher levels look more valuable
    s = context(0.99, 0.0, 5.0, 50.0, 0)
    assert pol.act(s, 0, 0.99, payment_pending=False) <= 1
    assert pol.act(context(0.99, 0.9, 5.0, 50.0, 0), 0, 0.99, payment_pending=False) <= 2
    assert pol.act(s, 0, 0.99, payment_pending=True) == 4


def test_policy_respects_gates():
    pol = LinUCBPolicy()
    pol.level_gates = [0, 0.9, 0.95, 0.99, 0.99]
    pol.b = [np.ones(8) * 10 for _ in range(5)]
    assert pol.act(context(0.5, 0.9, 5.0, 50.0, 0), 0, 0.5, payment_pending=True) == 0


def test_policy_ladder_only_goes_up(engine, sessions):
    scams, _ = sessions
    for r in engine.decide(scams):
        levels = [d["level"] for d in r["decisions"]]
        assert levels == sorted(levels)


def test_engine_ranks_scams_above_legit(engine, sessions):
    scams, legit = sessions
    top = lambda rs: [max(d["p"] for d in r["decisions"]) for r in rs]  # noqa: E731
    s, lg = np.array(top(engine.decide(scams))), np.array(top(engine.decide(legit)))
    auc = (s[:, None] > lg[None, :]).mean() + 0.5 * (s[:, None] == lg[None, :]).mean()
    assert auc > 0.9


def test_campaign_detector_flags_far_sessions():
    rng = np.random.default_rng(1)
    known = rng.normal(0, 0.05, (60, 8)) + np.eye(8)[0]
    det = CampaignDetector().fit(known, ["a"] * 60, [1] * 60, [["urgency"]] * 60)
    far = rng.normal(0, 0.05, (20, 8)) + np.eye(8)[3]
    assert det.is_unknown(far, np.ones(20)).all()
    assert not det.is_unknown(known[:10], np.ones(10)).any()
    sessions = [{"session_id": str(i), "language": "en", "channel": "sms",
                 "events": [{"type": "MSG_RECV", "text": "x", "tactics": ["fear"], "attrs": {}}]} for i in range(20)]
    cards = det.cluster(sessions, far)
    assert cards and cards[0]["size"] >= det.min_cluster
    assert det.psi([["fear"]] * 50) > det.psi([["urgency"]] * 50)
