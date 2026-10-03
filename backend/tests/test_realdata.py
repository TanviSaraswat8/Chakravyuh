"""Real-data governance: masking, PII indicators, de-duplication, leakage-safe splits, manifests,
adapters and validation. Uses tiny fixtures only (no network, no real datasets needed)."""

import json

import pytest

from chakravyuh.realdata import leakage, metrics, registry, validate
from chakravyuh.realdata.adapters import sp24_gateway_phishing
from chakravyuh.realdata.dedup import exact_groups, near_dup_clusters
from chakravyuh.realdata.pii import indicators
from chakravyuh.realdata.textnorm import dedup_key, masked, template_key

needs_registry = pytest.mark.skipif(not registry.REGISTRY.is_dir(),
                                    reason="data/registry not present (API image); runs in the repository and CI")


def test_shared_masking_removes_source_artefacts():
    a = masked("Your parcel <NAMED_ENTITY> is held, pay at https://x.ly/a1 or call 9876543210")
    b = masked("Your parcel #OTP is held, pay at www.evil.com/p or call +91 98765 43210")
    assert "<MASK>" in a and "<URL>" in a and "<NUM>" in a
    assert template_key(a) == template_key(b)
    assert "9876543210" not in a and "https" not in b


def test_pii_indicators():
    assert "upi_vpa" in indicators("send to ramesh.k@okaxis now")
    assert "phone_india" in indicators("call +91 98765 43210")
    assert "payment_card_luhn" in indicators("card 4111 1111 1111 1111")
    assert "payment_card_luhn" not in indicators("order 4111 1111 1111 1112")
    assert indicators("hello there") == set()


def test_exact_and_near_duplicates():
    texts = ["Dear customer your SBI account is blocked, update KYC at http://a.in/1",
             "Dear customer, your SBI account is BLOCKED. Update KYC at http://b.in/22",
             "Dear customer your SBI account is blocked update KYC now at http://c.in/333 today",
             "Lunch at 1? see you at the canteen"]
    ex = exact_groups(texts)
    assert ex[0] == ex[1] != ex[3]                       # same after masking + punctuation removal
    cl = near_dup_clusters(texts, threshold=0.6)
    assert cl[0] == cl[1] == cl[2] and cl[3] != cl[0]


def test_group_split_never_splits_a_cluster():
    recs = [{"text": f"m{i}"} for i in range(200)]
    clusters = [i // 5 for i in range(200)]               # 40 clusters of 5
    side = leakage.group_split(recs, clusters, test_frac=0.2, val_frac=0.1, seed=1)
    by_cluster = {}
    for c, s in zip(clusters, side):
        by_cluster.setdefault(c, set()).add(s)
    assert all(len(v) == 1 for v in by_cluster.values())
    assert {"train", "val", "test"} <= set(side)


def test_temporal_split_marks_seen_and_novel_campaigns():
    recs = [{"timestamp": f"2023-01-{d:02d}T00:00:00", "timestamp_quality": "unix_seconds"} for d in range(1, 21)]
    clusters = [0] * 10 + [0, 1, 1, 2, 2, 3, 3, 4, 4, 5]
    t = leakage.temporal_split(recs, clusters, "2023-01-11T00:00:00")
    assert t["counts"] == {"train": 10, "test": 10}
    assert t["test_seen_campaign"] == 1 and t["test_novel_campaign"] == 9


@needs_registry
def test_manifest_rules():
    m = registry.load("imc25_smishing")
    assert registry.manifest_problems(m) == []
    bad = dict(m, license_status="UNRESOLVED")
    assert any("licence" in p for p in registry.manifest_problems(bad))
    syn = dict(registry.load("paysim"), training_allowed=True)
    assert any("non-real" in p for p in registry.manifest_problems(syn))
    for i in registry.all_ids():                          # every committed manifest is complete and consistent
        assert registry.manifest_problems(registry.load(i)) == [], i


@needs_registry
def test_no_synthetic_dataset_is_marked_real():
    for i in registry.all_ids():
        m = registry.load(i)
        if i in ("paysim", "chakravyuh_simulator", "icfd_31k", "teleantifraud"):
            assert m["real_or_synthetic"] != "REAL", i


def test_sp24_adapter_parses_the_shifted_header(tmp_path):
    (tmp_path / "phishing_messages.csv").write_text(
        "messageID,objectID,destination number,message,time,error in time\n"
        '0,627001980f51cabb09ccf227,+447883196637,"Claim your prize https://x.vc/a",VIP Club,1651510753.0,7200.0\n',
        encoding="utf-8")
    r = list(sp24_gateway_phishing(tmp_path))[0]
    assert r["text"] == "Claim your prize https://x.vc/a"
    assert r["timestamp"].startswith("2022-05-02") and r["label"] == "scam"


@needs_registry
def test_validation_fails_on_tampered_raw_file(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "DATA", tmp_path)
    monkeypatch.setattr(registry, "REGISTRY", tmp_path / "registry")
    (tmp_path / "registry").mkdir()
    base = json.loads((registry.REPO / "data" / "registry" / "uci_sms_spam.json").read_text())
    raw = tmp_path / "real" / "messages" / "uci_sms_spam" / "raw"
    raw.mkdir(parents=True)
    f = raw / "SMSSpamCollection"
    f.write_text("ham\tsee you soon\nspam\tWIN a prize now call 09061701461\n", encoding="utf-8")
    base["sha256"] = {"SMSSpamCollection": registry.sha256_file(f)}
    base["sample_count"] = 2
    (tmp_path / "registry" / "uci_sms_spam.json").write_text(json.dumps(base))
    ok = validate.validate("uci_sms_spam")
    assert ok["hard_failures"] == [] and ok["checks"]["labels"] == {"legit": 1, "spam": 1}
    f.chmod(0o644)
    f.write_text("ham\tsee you soon\nham\tWIN a prize now\n", encoding="utf-8")
    bad = validate.validate("uci_sms_spam")
    assert any("SHA-256 mismatch" in x for x in bad["hard_failures"])


def test_single_class_tests_report_recall_only():
    r = metrics.detection([1, 1, 1, 1], [0.9, 0.8, 0.2, 0.7])
    assert r["recall"] == 0.75 and r["precision"] is None and r["fpr"] is None and r["roc_auc"] is None
    both = metrics.detection([1, 0, 1, 0], [0.9, 0.1, 0.4, 0.6])
    assert both["precision"] == 0.5 and both["fpr"] == 0.5 and both["roc_auc"] is not None


@pytest.mark.parametrize("text", ["", "a", "   "])
def test_degenerate_texts_do_not_crash(text):
    assert near_dup_clusters([text, text]) == near_dup_clusters([text, text])
    assert isinstance(dedup_key(text), str)


def test_experiment_text_variants_and_helpers():
    import numpy as np

    from chakravyuh.realdata import expkit as K
    rec = {"text": "Your parcel <NAMED_ENTITY> is held: https://x.ly/1 Itâ€™s urgent", "text_masked":
           masked("Your parcel <NAMED_ENTITY> is held: https://x.ly/1 Itâ€™s urgent")}
    assert "<MASK>" in K.variant(rec, "masked")
    assert "<" not in K.variant(rec, "stripped")
    assert "<" not in K.variant(rec, "clean")
    assert K.is_export_artefact({"text": "?image omitted"}) and not K.is_export_artefact({"text": "hello"})
    keep = K.purge_test_near_dups(["Your SBI account is blocked update KYC now at link"],
                                  ["Your SBI account is BLOCKED, update KYC now at link", "lunch at one?"])
    assert keep == [False, True]
    lo, hi = K.bootstrap_rate(np.array([0.0] * 90 + [1.0] * 10))
    assert lo < 0.1 < hi
    P = np.array([[0.9, 0.1], [0.6, 0.4]])
    assert 0 <= K.ece_top_label(P, np.array([0, 1])) <= 1
