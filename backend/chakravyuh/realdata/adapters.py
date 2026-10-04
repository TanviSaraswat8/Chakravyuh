"""Adapters: read one raw dataset (never modifying it) and yield canonical message records.

Canonical message schema, version msg-v1 (see docs/REAL_DATA_STRATEGY.md):
    record_id, dataset_id, source_row, text, label, label_raw, scam_type, lures, tactics,
    language, country, timestamp, timestamp_quality, year, sender_type, campaign_id, label_quality

label is one of: scam | legit | spam (unsolicited/marketing, not shown to be fraud) | unknown.
'spam' is never silently folded into 'scam' or 'legit'.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from .textnorm import template_key

PREPROCESSING_VERSION = "msg-v1"
LABELS = {"scam", "legit", "spam", "unknown"}

# IMC'25 lure principles (Stajano & Wilson) -> Chakravyuh tactic names. Only clear equivalents are
# mapped; 'distraction' and 'dishonesty' have no tactic in our taxonomy and stay as raw lures.
LURE_TO_TACTIC = {"authority": "authority", "time/urgency": "urgency", "need and greed": "greed",
                  "herd": "social_proof", "kindness": "reciprocity"}
YEAR = re.compile(r"\b(20[12]\d)\b")


def _rec(dataset_id: str, row: int, text: str, label: str, **kw) -> dict:
    assert label in LABELS, label
    base = {"record_id": f"{dataset_id}:{row}", "dataset_id": dataset_id, "source_row": row,
            "text": text, "label": label, "label_raw": None, "scam_type": None, "lures": [],
            "tactics": [], "language": None, "country": None, "timestamp": None,
            "timestamp_quality": "none", "year": None, "sender_type": None, "campaign_id": None,
            "label_quality": None}
    base.update(kw)
    return base


def _read_text(path: Path, encodings=("utf-8", "cp1252", "latin-1")) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in encodings:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _csv_rows(path: Path, **kw) -> Iterator[list[str]]:
    text, _ = _read_text(path)
    yield from csv.reader(io.StringIO(text, newline=""), **kw)


# ----------------------------------------------------------------------------------------------- IMC'25
def imc25_smishing(raw: Path) -> Iterator[dict]:
    rows = _csv_rows(raw / "final_dataset_output.csv")
    header = next(rows)
    ix = {h: i for i, h in enumerate(header)}
    def field(r: list[str], k: str) -> str | None:
        return (r[ix[k]].strip() or None) if ix[k] < len(r) else None

    for n, r in enumerate(rows):
        def g(k: str, r: list[str] = r) -> str | None:
            return field(r, k)
        st = (g("scam_type") or "").lower() or None
        lures = [x.strip() for x in (g("lure_principles") or "").split(",") if x.strip()]
        t = g("time") or ""
        y = YEAR.search(t)
        label = "unknown" if st is None else ("spam" if st == "spam" else "scam")
        yield _rec("imc25_smishing", n, g("text") or "", label, label_raw=st, scam_type=st, lures=lures,
                   tactics=sorted({LURE_TO_TACTIC[x] for x in lures if x in LURE_TO_TACTIC}),
                   language=(g("language") or "").lower() or None, country=g("original_network_country"),
                   timestamp=t or None,
                   timestamp_quality=("free_text_with_year" if y else "free_text") if t else "none",
                   year=int(y.group(1)) if y else None, sender_type=g("sender_id"),
                   label_quality="gpt-4o labels; kappa vs humans 0.93 scam type, 0.70 lures (150 English msgs)")


# --------------------------------------------------------------------------------------------- S&P'24
def sp24_gateway_phishing(raw: Path) -> Iterator[dict]:
    """Header names 6 columns but every row has 7: [row, object id, destination, text, sender, unix
    time, time error s]. Parsed positionally; pandas would silently shift the columns."""
    rows = _csv_rows(raw / "phishing_messages.csv")
    next(rows)
    for n, r in enumerate(rows):
        if len(r) != 7:
            continue                     # counted as malformed by the validator
        ts = datetime.fromtimestamp(float(r[5]), UTC).isoformat() if r[5] else None
        yield _rec("sp24_gateway_phishing", n, r[3], "scam", label_raw="phishing (VirusTotal/APWG URL verdict)",
                   timestamp=ts, timestamp_quality="unix_seconds" if ts else "none",
                   year=int(ts[:4]) if ts else None, sender_type="gateway", campaign_id=template_key(r[3]),
                   label_quality="URL reputation (VirusTotal/APWG); includes gambling promotions")


def sp24_campaigns(raw: Path) -> Iterator[dict]:
    rows = _csv_rows(raw / "phishing_campaigns.csv")
    header = next(rows)
    ix = {h: i for i, h in enumerate(header)}
    for n, r in enumerate(rows):
        yield {"campaign_row": n, "campaign_id": r[ix["campaignID"]], "template": r[ix["message"]],
               "n_messages": int(r[ix["number of messages"]]), "first_seen": float(r[ix["start timestamp"]]),
               "last_seen": float(r[ix["stop timestamp"]]), "urls": r[ix["urls"]]}


# ------------------------------------------------------------------------------------------ SMS corpora
def uci_sms_spam(raw: Path) -> Iterator[dict]:
    path = raw / "SMSSpamCollection"
    text, _ = _read_text(path)
    for n, line in enumerate(text.splitlines()):
        if "\t" not in line:
            continue
        lab, msg = line.split("\t", 1)
        yield _rec("uci_sms_spam", n, msg, "legit" if lab == "ham" else "spam", label_raw=lab,
                   language="en", year=2012, label_quality="manual (2012); 'spam' mixes marketing and scams")


def super_sms(raw: Path) -> Iterator[dict]:
    rows = _csv_rows(raw / "super_sms_dataset.csv")
    next(rows)
    for n, r in enumerate(rows):
        if len(r) < 2 or r[1] not in ("0", "1"):
            continue
        yield _rec("super_sms", n, r[0], "spam" if r[1] == "1" else "legit", label_raw=r[1],
                   label_quality="aggregated from earlier corpora; spam includes smishing and marketing")


def mishra_soni_smishing(raw: Path) -> Iterator[dict]:
    rows = _csv_rows(raw / "Dataset_5971.csv")
    next(rows)
    for n, r in enumerate(rows):
        lab = r[0].strip().lower()
        label = {"ham": "legit", "smishing": "scam", "spam": "spam"}.get(lab, "unknown")
        yield _rec("mishra_soni_smishing", n, r[1], label, label_raw=r[0], language="en",
                   label_quality="manual; ~85% of texts re-used from UCI")


def smishtank(raw: Path) -> Iterator[dict]:
    rows = _csv_rows(raw / "smishtank.csv")
    header = next(rows)
    ix = {h: i for i, h in enumerate(header)}
    for n, r in enumerate(rows):
        cats = r[ix["Message Categories"]] if "Message Categories" in ix else ""
        label = "spam" if "advert" in cats.lower() else "scam"
        t = r[ix["timeReceived"]] if "timeReceived" in ix else ""
        try:
            ts = datetime.strptime(t, "%m/%d/%Y, %H:%M:%S").replace(tzinfo=UTC).isoformat()
        except ValueError:
            ts = None
        yield _rec("smishtank", n, r[ix["MainText"]], label, label_raw=cats or None, scam_type=cats or None,
                   language="en", country="USA", timestamp=ts, timestamp_quality="report_time" if ts else "none",
                   year=int(ts[:4]) if ts else None, sender_type=r[ix["SenderType"]] if "SenderType" in ix else None,
                   label_quality="user-reported smishing; categories by SmishTank analysts")


def nus_sms_corpus(raw: Path) -> Iterator[dict]:
    """Personal SMS donated by volunteers (no scam labels). Treated as 'legit' with
    label_quality 'assumed_ham'."""
    with zipfile.ZipFile(raw / "smsCorpus_en_xml_2015.03.09_all.zip") as z:
        xml = z.read("smsCorpus_en_2015.03.09_all.xml")
    root = ElementTree.fromstring(xml)
    for n, m in enumerate(root.iter("message")):
        txt = (m.findtext("text") or "").strip()
        country = m.findtext("source/userProfile/country")
        coll = m.find("collectionMethod")
        y = YEAR.search(coll.get("time", "")) if coll is not None else None
        yield _rec("nus_sms_corpus", n, txt, "legit", label_raw="unlabelled personal SMS", language="en",
                   country=country, year=int(y.group(1)) if y else None,
                   label_quality="assumed_ham (volunteer personal messages, not individually labelled)")


def moz_smishing(raw: Path) -> Iterator[dict]:
    """Expected after local download from Hugging Face (MOZNLP/MOZ-Smishing). Column names are checked
    at registration; the adapter refuses unknown layouts instead of guessing."""
    files = sorted(p for p in raw.iterdir()
                   if p.suffix in (".csv", ".tsv", ".jsonl", ".json") and not p.name.startswith("."))
    if not files:
        raise FileNotFoundError("MOZ-Smishing raw files not found; see scripts/fetch_real_datasets.py status")
    n = 0
    for f in files:
        rows = _csv_rows(f, delimiter="\t" if f.suffix == ".tsv" else ",")
        header = [h.strip().lower() for h in next(rows)]
        tcol = next((header.index(c) for c in ("text", "sms", "message") if c in header), None)
        lcol = next((header.index(c) for c in ("label", "class", "category") if c in header), None)
        if tcol is None or lcol is None:
            raise ValueError(f"{f.name}: unexpected columns {header}; update the adapter after inspecting")
        for r in rows:
            lab = r[lcol].strip().lower()
            label = {"ham": "legit", "0": "legit", "legit": "legit", "legitimate": "legit", "spam": "scam",
                     "smishing": "scam", "1": "scam"}.get(lab, "unknown")
            yield _rec("moz_smishing", n, r[tcol], label, label_raw=lab, language="pt", country="MOZ",
                       label_quality="manual annotation (paper); 'spam' = mobile-money smishing")
            n += 1


def india_spam_sms_junioralive(raw: Path) -> Iterator[dict]:
    rows = _csv_rows(raw / "spam_ham_india.csv")
    next(rows)
    for n, r in enumerate(rows):
        if len(r) < 2 or r[1].strip().lower() not in ("ham", "spam"):
            continue
        lab = r[1].strip().lower()
        yield _rec("india_spam_sms_junioralive", n, r[0], "legit" if lab == "ham" else "spam", label_raw=lab,
                   country="IND", label_quality="community crowd-sourced; protocol undocumented; spam = promotions")


ADAPTERS = {
    "imc25_smishing": imc25_smishing,
    "sp24_gateway_phishing": sp24_gateway_phishing,
    "uci_sms_spam": uci_sms_spam,
    "super_sms": super_sms,
    "mishra_soni_smishing": mishra_soni_smishing,
    "smishtank": smishtank,
    "nus_sms_corpus": nus_sms_corpus,
    "moz_smishing": moz_smishing,
    "india_spam_sms_junioralive": india_spam_sms_junioralive,
}
