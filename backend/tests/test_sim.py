"""Simulator tests: sessions are well-formed, labels are right, evolution behaves."""

import random

from chakravyuh.sim.agents import Genome, Victim, build_script, random_genome, run_session
from chakravyuh.sim.evolution import crossover, evaluate, genome_vector, mutate, next_generation
from chakravyuh.sim.sandbox import PaymentSandbox
from chakravyuh.sim.simulator import Chakravyuh, rule_detector
from chakravyuh.sim.taxonomy import BENIGN_FAMILIES, EVENT_TYPES, SCAM_FAMILIES, STAGES, TACTICS


def _sim(seed=1):
    return Chakravyuh(seed=seed)


def test_every_family_produces_valid_sessions():
    sim = _sim()
    for fam in SCAM_FAMILIES + BENIGN_FAMILIES:
        for lang in ("en", "hi", "hinglish"):
            s = sim.play(Genome(family=fam, language=lang))
            assert s["label"] == int(fam in SCAM_FAMILIES)
            assert s["events"], fam
            times = [e["t"] for e in s["events"]]
            assert times == sorted(times), "events must be in time order"
            for e in s["events"]:
                assert e["type"] in EVENT_TYPES
                assert e["stage"] in STAGES
                assert set(e["tactics"]) <= set(TACTICS)


def test_legit_sessions_never_lose_money():
    sim = _sim(2)
    for _ in range(60):
        s = sim.play(random_genome(sim.rng, BENIGN_FAMILIES))
        assert s["loss"] == 0.0


def test_wording_holdout_separates_train_and_test_variants():
    sim = _sim(3)
    g = Genome(family="investment_group", language="en")
    train_texts = {e["text"] for _ in range(30) for e in sim.play(g, pool="train")["events"] if e["type"] == "MSG_RECV"}
    test_texts = {e["text"] for _ in range(30) for e in sim.play(g, pool="test")["events"] if e["type"] == "MSG_RECV"}
    # The contact step has two English variants: the last one is reserved for test sessions.
    assert any(t.startswith("Hi! Our mentor") for t in test_texts)
    assert not any(t.startswith("Hi! Our mentor") for t in train_texts)


def test_warnings_reduce_payment_probability():
    v = Victim("u@okbank", "60+", 0.3, 0.7, 0.8, "en", 2000)
    tactics = ["authority", "fear", "urgency"]
    probs = [v.pay_probability(tactics, warned=w) for w in range(5)]
    assert probs == sorted(probs, reverse=True)
    assert probs[4] < probs[0] / 3


def test_mule_payments_are_forwarded():
    rng = random.Random(0)
    sb = PaymentSandbox(rng)
    sb.build_world(n_users=20, n_merchants=5, n_mule_rings=2)
    mule = sb.scam_payee()
    before = len(sb.ledger)
    sb.pay(sb.users()[0], mule, 5000, t=100.0)
    hops = sb.ledger[before:]
    assert len(hops) == 3   # victim -> layer 1 -> layer 2 -> exchange
    assert hops[1].src == mule and sb.accounts[hops[1].dst].kind == "mule_l2"


def test_disguised_opener_is_marked():
    g = Genome(family="task_job", borrow_contact="investment_genuine")
    script = build_script(g)
    assert script[0].get("disguise") is True
    s = _sim(4).play(g)
    first_msgs = [e for e in s["events"] if e["stage"] == "contact"]
    assert all(e["attrs"].get("disguise") for e in first_msgs)


def test_mutation_and_crossover_change_genomes():
    rng = random.Random(5)
    a = random_genome(rng, SCAM_FAMILIES)
    b = random_genome(rng, SCAM_FAMILIES)
    children = [mutate(a, rng, 2, SCAM_FAMILIES) for _ in range(20)]
    assert any(genome_vector(c) != genome_vector(a) for c in children)
    child = crossover(a, b, rng, 2)
    assert child.generation == 2 and child.parent.startswith(a.genome_id)


def test_fitness_rewards_evasion():
    sim = _sim(6)
    g = Genome(family="digital_arrest")
    sessions = [sim.play(g) for _ in range(5)]
    caught = evaluate(g, sessions, lambda s: 1.0, [], novelty_weight=0)
    missed = evaluate(g, sessions, lambda s: 0.0, [], novelty_weight=0)
    assert missed.fitness >= caught.fitness
    nxt = next_generation([caught, missed], random.Random(0), 2, SCAM_FAMILIES, size=6)
    assert len(nxt) == 6


def test_rule_detector_is_a_probability():
    sim = _sim(7)
    for _ in range(20):
        s = sim.play(random_genome(sim.rng, SCAM_FAMILIES + BENIGN_FAMILIES))
        assert 0.0 <= rule_detector(s) <= 1.0


def test_run_session_is_deterministic_for_a_seed():
    def one():
        rng = random.Random(11)
        sb = PaymentSandbox(rng)
        sb.build_world(n_users=30, n_merchants=5, n_mule_rings=2)
        v = Victim.sample(rng, sb.users()[0], "en")
        s = run_session(Genome(family="fake_kyc", genome_id="x"), v, sb, rng, 0.0)
        return [(e["type"], e["text"]) for e in s["events"]]
    assert one() == one()


def test_public_export_drops_text_and_payees(tmp_path):
    import gzip
    import json

    from chakravyuh.sim.export_public import anonymise

    sim = _sim(8)
    s = sim.play(Genome(family="investment_group"))
    s["split_hint"] = "train_pool"
    pub = anonymise(s)
    blob = json.dumps(pub)
    assert "text" not in {k for e in pub["events"] for k in e}
    assert "@" not in blob, "no UPI handles (payee or victim IDs) may appear"
    assert all("payee" not in e["attrs"] for e in pub["events"]) and "genome" not in pub
    assert pub["session_id"] != s["session_id"]
    assert gzip  # imported for the module under test
