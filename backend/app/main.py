"""Chakravyuh API.

Run locally:   uvicorn app.main:app --reload   (from the backend/ folder)
Docs:          http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .routers import beta, demo, intel, sessions
from .services.scoring import get_engine, model_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    get_engine()          # load models once at startup
    yield


app = FastAPI(
    title="Chakravyuh API",
    version="0.1.0",
    description="Scam-session detection for UPI, banking and wallets: live scoring, alerts, "
                "emerging-campaign detection and the attacker-vs-defender arena.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(sessions.router)
app.include_router(intel.router)
app.include_router(demo.router)
app.include_router(beta.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "env": settings.env, "model": model_status()}
