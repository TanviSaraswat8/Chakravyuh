"""Shared test setup: fresh rate limits for every test."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.security.ratelimit import limiter
    limiter.reset()
    yield
    limiter.reset()
