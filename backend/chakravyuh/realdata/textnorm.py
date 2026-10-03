"""Text normalisation shared by validation, de-duplication and leakage auditing.

The same masking is applied to every source. Without it a classifier can learn which dataset a
message came from (for example IMC'25 masks names as <NAMED_ENTITY>, other corpora don't) instead of
whether it is a scam.
"""

from __future__ import annotations

import re
import unicodedata

URL = re.compile(r"(?i)\b(?:https?://|hxxps?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|in|ly|me|io|co|uk|info|xyz|top|site|online|link|app|cc|vc|us|club|shop)(?:/\S*)?\b")
EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
VPA = re.compile(r"(?i)\b[\w.-]{2,}@(?:ok\w+|ybl|paytm|upi|ibl|axl|apl|ptyes|ptsbi|ptaxis|pthdfc|sbi|icici|hdfcbank|axisbank|kotak|yesbank|freecharge|jio|airtel|fbl|idfcbank|barodampay|unionbank)\b")
NUM = re.compile(r"(?<![A-Za-z])\+?\d[\d\s\-().]{2,}\d(?![A-Za-z])|\d")
# Mask tokens used by source datasets, mapped to one shared vocabulary.
SOURCE_MASKS = re.compile(r"<(?:URL|PHONE_NUMBER|EMAIL_ADDRESS|DATE_TIME|NAMED_ENTITY|PERSON|LOCATION|"
                          r"US_DRIVER_LICENSE|CREDIT_CARD|IBAN_CODE|IP_ADDRESS|NRP|US_SSN|[A-Z_]{3,30})>|"
                          r"#(?:URL|OTP|NUM)\b")
SPACE = re.compile(r"\s+")
PUNCT = re.compile(r"[^\w<>\s]", re.UNICODE)


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def masked(text: str) -> str:
    """Shared masking: URLs, e-mails, UPI IDs and digit runs become <URL>/<EMAIL>/<VPA>/<NUM>; any
    source-specific mask token becomes <MASK>. Case and wording are kept (for models)."""
    t = nfkc(text)
    t = SOURCE_MASKS.sub(" <MASK> ", t)
    t = URL.sub(" <URL> ", t)
    t = VPA.sub(" <VPA> ", t)
    t = EMAIL.sub(" <EMAIL> ", t)
    t = NUM.sub(" <NUM> ", t)
    t = re.sub(r"(?:<NUM>\s*){2,}", "<NUM> ", t)
    return SPACE.sub(" ", t).strip()


def dedup_key(text: str) -> str:
    """Aggressive key for exact-duplicate detection: masked, lower-cased, punctuation removed."""
    t = masked(text).lower()
    t = PUNCT.sub(" ", t)
    return SPACE.sub(" ", t).strip()


def template_key(text: str) -> str:
    """Template signature: like dedup_key but every mask token collapses to one placeholder, so
    messages that differ only in links, numbers or names share a template."""
    return re.sub(r"<[a-z]+>", "<x>", dedup_key(text))


def shingles(text: str, k: int = 5) -> set[str]:
    t = dedup_key(text)
    if len(t) <= k:
        return {t} if t else set()
    return {t[i:i + k] for i in range(len(t) - k + 1)}
