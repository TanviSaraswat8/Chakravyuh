#!/usr/bin/env python3
"""Regression checks for fixes found in testing. Standard library only.

    python3 scripts/e2e_checks.py http://localhost:8000              # hold + flat-deposit checks
    python3 scripts/e2e_checks.py http://localhost:8000 --privacy    # also privacy mode (server must run
                                                                     # with STORE_MESSAGE_TEXT=false)

1. A screen-shared "Customs" call followed by a Rs 30,000 scam payment must be put on hold (level 4)
   by the time the UPI app opens.
2. A genuine Rs 90,000 flat deposit to a new payee must never get a hold (level 3 or 4).
3. Privacy mode: risk revealed by an earlier message must survive later events, while the message
   text is never stored.
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = next((a for a in sys.argv[1:] if not a.startswith("--")), "http://localhost:8000").rstrip("/")
PRIVACY = "--privacy" in sys.argv
failures: list[str] = []


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def run(events: list[dict]) -> tuple[str, list[tuple[str, int, float]]]:
    sid = call("POST", "/v1/sessions", {"language": "en", "channel": "whatsapp"})["id"]
    out = []
    for i, e in enumerate(events):
        r = call("POST", f"/v1/sessions/{sid}/events", {**e, "t": (i + 1) * 120})
        out.append((e["type"], r["latest"]["level"], round(r["latest"]["p"], 3)))
    return sid, out


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'} {name}: {detail}")
    if not ok:
        failures.append(name)


def main() -> int:
    print(f"Regression checks against {BASE}")
    _, out = run([
        {"type": "MSG_RECV", "attrs": {"known_sender": False},
         "text": "This is the Customs Department. A parcel in your name contains illegal items. Stay on the line."},
        {"type": "CALL", "attrs": {"known": False, "minutes": 45}},
        {"type": "SCREEN_SHARE"},
        {"type": "UPI_OPEN"},
        {"type": "PAYEE_NEW", "attrs": {"payee": "acc00042@ybl", "payee_age_days": 6}},
        {"type": "PAY", "attrs": {"amount": 30000, "amount_ratio": 20, "payee": "acc00042@ybl", "first_time": True}},
    ])
    upi = next(level for t, level, _ in out if t == "UPI_OPEN")
    check("Customs scam held when UPI opens", upi == 4, f"level {upi} at UPI open (4 = hold); trace {out}")

    _, out = run([
        {"type": "MSG_RECV", "attrs": {"known_sender": False},
         "text": "Hi, the flat is yours. Please transfer the security deposit of Rs 90,000 today so I can hold it."},
        {"type": "CALL", "attrs": {"known": False, "minutes": 8}},
        {"type": "UPI_OPEN"},
        {"type": "PAYEE_NEW", "attrs": {"payee": "shop99999@paytm", "payee_age_days": 400}},
        {"type": "PAY", "attrs": {"amount": 90000, "amount_ratio": 60, "payee": "shop99999@paytm", "first_time": True}},
    ])
    top = max(level for _, level, _ in out)
    check("Genuine flat deposit not held", top < 3, f"highest level {top} (3+ would pause the payment)")

    if PRIVACY:
        sid, out = run([
            {"type": "MSG_RECV", "text": "This is CBI. A parcel in your name contains illegal items. Stay on the line."},
            {"type": "CALL", "attrs": {"known": False, "minutes": 60}},
            {"type": "SCREEN_SHARE"},
            {"type": "UPI_OPEN"},
        ])
        stored = call("GET", f"/v1/sessions/{sid}")["events"]
        text_stored = any(e["text"] for e in stored if e["type"] == "MSG_RECV")
        p_last = out[-1][2]
        check("Privacy mode keeps risk", p_last > 0.5, f"risk {p_last} after later events")
        check("Privacy mode stores no text", not text_stored, "message text absent from stored events")
        print(f"  session {sid} (inspect it in the database to confirm)")

    print("PASSED" if not failures else f"FAILED ({len(failures)}): {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
