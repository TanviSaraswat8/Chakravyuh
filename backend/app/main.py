"""Chakravyuh API.

Run locally:   uvicorn app.main:app --reload   (from the backend/ folder)
Docs:          http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import check_settings, settings
from .db import SessionLocal, init_db
from .routers import admin, auth, beta, demo, intel, sessions
from .security.middleware import SecurityHeadersMiddleware
from .services.scoring import get_engine, model_status
from .services.users import bootstrap_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_settings()      # refuse unsafe cookie / bootstrap settings before serving anything
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)
    get_engine()          # load models once at startup (only if their SHA-256 digests match)
    yield


app = FastAPI(
    title="Chakravyuh API",
    version="0.1.0",
    description="Scam-session detection for UPI, banking and wallets: live scoring, alerts, "
                "emerging-campaign detection and the attacker-vs-defender arena.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "X-API-Key", "X-Request-ID"],
                   expose_headers=["X-Request-ID", "Retry-After", "X-Step-Up-Required"])
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(sessions.router)
app.include_router(intel.router)
app.include_router(demo.router)
app.include_router(beta.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "env": settings.env, "model": model_status()}
