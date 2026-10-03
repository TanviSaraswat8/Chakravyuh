"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


ENV = os.getenv("CHAKRAVYUH_ENV", "development")

# Hard ceiling for POST /v1/demo/arena/adapt?epochs=. The co-evolution CLI defaults to 4 epochs; one
# adapt costs ~8 s fixed plus ~1-1.5 s per epoch on a 4-vCPU machine, so 8 epochs stays under ~20 s there
# (a few times that on a slow laptop) while leaving room above the default.
MAX_ADAPT_EPOCHS = 8


@dataclass(frozen=True)
class Settings:
    env: str = ENV
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'chakravyuh.db'}")
    artifacts_dir: str = os.getenv("CHAKRAVYUH_ARTIFACTS", str(BACKEND_DIR / "artifacts"))
    data_dir: str = os.getenv("CHAKRAVYUH_DATA", str(BACKEND_DIR / "data"))
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if o.strip()])
    store_message_text: bool = _bool("STORE_MESSAGE_TEXT", True)   # set false in production for privacy

    # Authentication (cookie sessions). Secure cookies are the default in production; plain-HTTP
    # localhost development needs COOKIE_SECURE=false, which production refuses.
    cookie_secure: bool = _bool("COOKIE_SECURE", ENV == "production")
    cookie_samesite: str = os.getenv("COOKIE_SAMESITE", "lax").lower()       # lax | strict | none
    session_ttl_minutes: int = int(os.getenv("SESSION_TTL_MINUTES", "480"))   # absolute lifetime
    session_idle_minutes: int = int(os.getenv("SESSION_IDLE_MINUTES", "120"))  # inactivity timeout
    reauth_window_seconds: int = int(os.getenv("REAUTH_WINDOW_SECONDS", "300"))  # step-up freshness
    allow_registration: bool = _bool("ALLOW_REGISTRATION", True)              # self sign-up as ANALYST

    # First administrator. Both must be set together; a weak password stops the API from starting.
    bootstrap_admin_email: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
    bootstrap_admin_password: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    # Retired: the shared admin key is no longer accepted anywhere. Kept only to warn when it is set.
    legacy_admin_api_key_set: bool = bool(os.getenv("ADMIN_API_KEY"))

    rate_limits_enabled: bool = _bool("RATE_LIMITS_ENABLED", True)
    # Only enable behind a reverse proxy you control (nginx in docker compose, Render's proxy).
    trust_forwarded_for: bool = _bool("TRUST_FORWARDED_FOR", False)


settings = Settings()


def check_settings(s: Settings = settings) -> None:
    """Refuse unsafe combinations at startup instead of running with them."""
    if s.cookie_samesite not in ("lax", "strict", "none"):
        raise RuntimeError("COOKIE_SAMESITE must be lax, strict or none")
    if s.cookie_samesite == "none" and not s.cookie_secure:
        raise RuntimeError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
    if s.env == "production" and not s.cookie_secure:
        raise RuntimeError("COOKIE_SECURE=false is not allowed when CHAKRAVYUH_ENV=production")
    if bool(s.bootstrap_admin_email) != bool(s.bootstrap_admin_password):
        raise RuntimeError("Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, or neither")
