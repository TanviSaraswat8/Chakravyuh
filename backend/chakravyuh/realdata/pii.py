"""PII indicators. Detection only: raw data is never modified. Patterns are heuristics and will
produce false positives (e.g. order numbers that look like phone numbers); counts are indicators."""

from __future__ import annotations

import re

PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"(?i)\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b"),
    "upi_vpa": re.compile(r"(?i)\b[\w.-]{2,}@(?:ok\w+|ybl|paytm|upi|ibl|axl|apl|sbi|icici|hdfcbank|axisbank|"
                          r"kotak|yesbank|jio|airtel|fbl|idfcbank)\b"),
    "phone_india": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    "phone_intl": re.compile(r"(?<!\d)\+\d{1,3}[\s-]?\d[\d\s-]{7,13}\d(?!\d)"),
    "aadhaar_like": re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "pan_like": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "ifsc_like": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
    "url": re.compile(r"(?i)\b(?:https?://|www\.)\S+"),
}
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _luhn(digits: str) -> bool:
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        s += d
        alt = not alt
    return s % 10 == 0


def indicators(text: str) -> set[str]:
    found = {name for name, rx in PATTERNS.items() if rx.search(text or "")}
    for m in _CARD.finditer(text or ""):
        d = re.sub(r"\D", "", m.group())
        if 13 <= len(d) <= 19 and _luhn(d):
            found.add("payment_card_luhn")
            break
    return found
