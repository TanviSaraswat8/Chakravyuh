"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("CHAKRAVYUH_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'chakravyuh.db'}")
    artifacts_dir: str = os.getenv("CHAKRAVYUH_ARTIFACTS", str(BACKEND_DIR / "artifacts"))
    data_dir: str = os.getenv("CHAKRAVYUH_DATA", str(BACKEND_DIR / "data"))
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if o.strip()])
    require_api_key: bool = _bool("REQUIRE_API_KEY", False)
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "change-me-admin")
    store_message_text: bool = _bool("STORE_MESSAGE_TEXT", True)   # set false in production for privacy


settings = Settings()
