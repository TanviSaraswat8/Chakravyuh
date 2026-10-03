"""Mutation operators.

Text mutations change surface form (what scammers do to dodge keyword filters).
Genome mutations change the scam's structure (new pretext, reordered tactics,
different channel or language) - this is how new "emerging" variants appear.
"""

from __future__ import annotations

import random
import re

SYNONYMS = {
    "transfer": ["send", "move", "deposit", "pay"],
    "urgent": ["immediately", "right now", "asap", "today itself"],
    "account": ["a/c", "acct", "wallet"],
    "profit": ["returns", "gains", "earnings", "income"],
    "blocked": ["suspended", "frozen", "deactivated", "closed"],
    "payment": ["amount", "fund", "money"],
    "verify": ["validate", "confirm", "authenticate"],
    "tax": ["fee", "charge", "GST"],
}
HINGLISH_SWAPS = {
    "now": "abhi", "money": "paise", "send": "bhejo", "today": "aaj", "please": "plz",
    "quickly": "jaldi", "your": "aapka", "don't": "mat", "family": "ghar wale",
}
LEET = {"a": "@", "o": "0", "i": "1", "e": "3", "s": "$"}
EMOJIS = ["🔥", "✅", "💰", "⚠️", "🚨", "📈", "🙏", "👉"]


def _swap_words(text: str, table: dict, rng: random.Random, p: float) -> str:
    def repl(m: re.Match) -> str:
        w = m.group(0)
        key = w.lower()
        if key in table and rng.random() < p:
            v = table[key]
            v = rng.choice(v) if isinstance(v, list) else v
            return v.capitalize() if w[0].isupper() else v
        return w
    return re.sub(r"[A-Za-z']+", repl, text)


def synonym(text: str, rng: random.Random) -> str:
    return _swap_words(text, SYNONYMS, rng, 0.7)


def code_mix(text: str, rng: random.Random) -> str:
    return _swap_words(text, HINGLISH_SWAPS, rng, 0.6)


def obfuscate(text: str, rng: random.Random) -> str:
    """Leetspeak / spacing tricks on keywords that filters look for."""
    keys = ["transfer", "pay", "otp", "pin", "kyc", "blocked", "profit", "upi"]
    out = text
    for k in keys:
        if k in out.lower() and rng.random() < 0.6:
            idx = out.lower().index(k)
            word = out[idx:idx + len(k)]
            if rng.random() < 0.5:
                new = "".join(LEET.get(c.lower(), c) if rng.random() < 0.5 else c for c in word)
            else:
                new = ".".join(word)
            out = out[:idx] + new + out[idx + len(k):]
    return out


def typos(text: str, rng: random.Random) -> str:
    chars = list(text)
    for _ in range(max(1, len(chars) // 40)):
        i = rng.randrange(len(chars))
        if chars[i].isalpha():
            chars[i] = ""
    return "".join(chars)


def emoji(text: str, rng: random.Random) -> str:
    return f"{rng.choice(EMOJIS)} {text} {rng.choice(EMOJIS)}"


TEXT_MUTATIONS = {
    "synonym": synonym,
    "code_mix": code_mix,
    "obfuscate": obfuscate,
    "typos": typos,
    "emoji": emoji,
}


def mutate_text(text: str, ops: list[str], rng: random.Random) -> str:
    for op in ops:
        text = TEXT_MUTATIONS[op](text, rng)
    return text
