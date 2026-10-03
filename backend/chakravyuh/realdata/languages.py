"""Measured language distribution. Uses the dataset's own language field where it has one, otherwise
langid.py (optional dependency). Romanised Hindi (Hinglish) is invisible to standard language ID, so a
separate lexical heuristic counts *candidate* Hinglish messages; it is an estimate, not a label."""

from __future__ import annotations

import re
from collections import Counter

HINGLISH = {"hai", "hain", "aap", "aapka", "aapke", "apna", "apne", "kya", "nahi", "nahin", "karo", "kare", "karein",
            "kijiye", "ke", "ki", "ka", "se", "mein", "par", "ko", "abhi", "jaldi", "paise", "rupaye", "bhai",
            "ji", "haan", "kar", "raha", "rahe", "hoga", "gaya", "milega", "jayega", "turant", "khata", "band"}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
WORD = re.compile(r"[a-z]+")


def _langid():
    try:
        import langid
        return langid
    except ImportError:
        return None


def language_report(recs: list[dict], sample: int = 20000) -> dict:
    have = [r.get("language") for r in recs if r.get("language")]
    li = _langid()
    if len(have) >= 0.9 * len(recs):
        dist, method = Counter(have), "dataset field"
    elif li:
        dist = Counter(li.classify(r["text"])[0] for r in recs[:sample] if r["text"])
        method = f"langid.py on first {min(sample, len(recs))} records"
    else:
        dist, method = Counter(), "unavailable (pip install langid)"
    hinglish = 0
    devanagari = 0
    for r in recs:
        t = r["text"] or ""
        if DEVANAGARI.search(t):
            devanagari += 1
        words = WORD.findall(t.lower())
        if len(words) >= 4 and sum(w in HINGLISH for w in words) / len(words) >= 0.2:
            hinglish += 1
    total = sum(dist.values()) or 1
    return {"method": method, "top": {k: v for k, v in dist.most_common(12)},
            "share_top": {k: round(v / total, 4) for k, v in dist.most_common(5)},
            "devanagari_records": devanagari, "hinglish_candidates_heuristic": hinglish}
