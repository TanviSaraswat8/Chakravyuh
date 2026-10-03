"""Signing in as a given role in tests."""

from __future__ import annotations

import uuid

PASSWORD = "correct horse battery staple"


def make_user(role: str = "ANALYST", email: str | None = None, password: str = PASSWORD):
    from app.db import SessionLocal
    from app.services.users import create_user
    email = email or f"{role.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        return create_user(db, email, password, role)


def sign_in(client, role: str = "ANALYST", password: str = PASSWORD):
    """Create a user with `role`, sign `client` in, and send the CSRF token on every later request."""
    u = make_user(role, password=password)
    r = client.post("/v1/auth/login", json={"email": u.email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return u
