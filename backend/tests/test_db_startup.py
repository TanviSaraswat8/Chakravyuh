"""The API must survive PostgreSQL refusing connections for a while at boot (Docker first start)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app import db


def _refused() -> OperationalError:
    return OperationalError("connect", {}, Exception("connection refused"))


def test_init_db_waits_for_database(monkeypatch):
    calls = {"n": 0}

    def flaky_create_all(_engine):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _refused()

    monkeypatch.setattr(db.Base.metadata, "create_all", flaky_create_all)
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)
    db.init_db(timeout_s=60)
    assert calls["n"] == 3


def test_init_db_gives_up_with_the_real_error(monkeypatch):
    def always_refused(_engine):
        raise _refused()

    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(db.Base.metadata, "create_all", always_refused)
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)
    monkeypatch.setattr(db.time, "monotonic", lambda: next(clock))
    with pytest.raises(OperationalError, match="connection refused"):
        db.init_db(timeout_s=30)
