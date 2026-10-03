#!/usr/bin/env python3
"""End-to-end smoke test for a running Chakravyuh API. Standard library only.

    python3 scripts/smoke_test.py http://localhost:8000
    python3 scripts/smoke_test.py https://chakravyuh-api.onrender.com

Exits non-zero if any check fails. Safe to run against production: it creates one test session,
one beta sign-up (random email) and one feedback entry.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
failures: list[str] = []


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    print(f"Smoke-testing {BASE}")
    t0 = time.time()

    code, h = call("GET", "/health")
    check("health responds", code == 200 and h.get("status") == "ok", str(h))
    check("models are loaded", h.get("model", {}).get("loaded") is True, str(h.get("model")))

    code, sc = call("GET", "/v1/demo/scenarios")
    check("demo scenarios listed", code == 200 and len(sc) >= 5)

    code, s = call("GET", "/v1/demo/scenarios/investment_group")
    levels = [x["level"] for x in s.get("scores", [])]
    check("scam scenario escalates", code == 200 and max(levels, default=0) >= 1, str(levels))

    code, s = call("GET", "/v1/demo/scenarios/big_purchase")
    levels = [x["level"] for x in s.get("scores", [])]
    check("legitimate look-alike stays quiet", code == 200 and max(levels, default=1) == 0, str(levels))

    code, sess = call("POST", "/v1/sessions", {"language": "en", "channel": "sms", "source": "live"})
    check("session created", code == 201 and "id" in sess)
    last: dict = {}
    if code == 201:
        events = [
            {"type": "MSG_RECV", "text": "This is CBI. A parcel in your name contains illegal items. Stay on the line."},
            {"type": "CALL", "attrs": {"known": False, "minutes": 60}},
            {"type": "SCREEN_SHARE"},
            {"type": "UPI_OPEN"},
        ]
        for i, e in enumerate(events):
            code, last = call("POST", f"/v1/sessions/{sess['id']}/events", {**e, "t": i * 120})
        check("live session raises an alert", last.get("latest", {}).get("level", 0) >= 1, str(last.get("latest")))
        code, detail = call("GET", f"/v1/sessions/{sess['id']}")
        check("session stored in the database", code == 200 and len(detail.get("events", [])) == 4)
        if detail.get("alerts"):
            code, a = call("POST", f"/v1/alerts/{detail['alerts'][0]['id']}/respond", {"response": "cancelled"})
            check("alert response recorded", code == 200 and a.get("response") == "cancelled")

    code, r = call("POST", "/v1/score", {"language": "en", "events": [
        {"type": "MSG_RECV", "client_tags": {"tactics": ["authority", "fear"], "p_scam": 0.95}},
        {"type": "UPI_OPEN"}]})
    check("privacy mode (on-device tags) scores", code == 200 and r.get("latest", {}).get("p", 0) > 0.5)

    code, b = call("POST", "/v1/beta/signup", {"email": f"smoke-{uuid.uuid4().hex[:8]}@example.com", "name": "Smoke"})
    check("beta sign-up issues a key", code == 201 and b.get("api_key", "").startswith("ck_"))
    if code == 201:
        code, _ = call("POST", "/v1/beta/feedback", {"kind": "general", "rating": 5, "comment": "smoke test"},
                       {"X-API-Key": b["api_key"]})
        check("feedback accepted", code == 201)

    code, m = call("GET", "/v1/metrics")
    check("metrics available", code == 200 and m.get("sessions", 0) >= 1)
    code, meta = call("GET", "/v1/meta")
    check("benchmark report published", code == 200 and "test_seen" in meta.get("benchmark", {}))

    print(f"{'PASSED' if not failures else 'FAILED'} in {time.time() - t0:.1f}s"
          + (f" ({len(failures)} failed: {', '.join(failures)})" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
