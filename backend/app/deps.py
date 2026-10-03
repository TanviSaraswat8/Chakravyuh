"""Auth dependencies: tester API keys for alpha/beta, an admin key for analyst-only routes."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import BetaTester


def current_tester(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> BetaTester | None:
    if not x_api_key:
        if settings.require_api_key:
            raise HTTPException(401, "Missing X-API-Key header")
        return None
    tester = db.scalar(select(BetaTester).where(BetaTester.api_key == x_api_key))
    if tester is None and x_api_key != settings.admin_api_key:
        raise HTTPException(401, "Invalid API key")
    return tester


def require_admin(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> None:
    if x_api_key == settings.admin_api_key:
        return
    tester = db.scalar(select(BetaTester).where(BetaTester.api_key == x_api_key)) if x_api_key else None
    if tester is None or tester.role not in ("analyst", "admin"):
        raise HTTPException(403, "Analyst or admin key required")
