"""Database engine and session factory. SQLite locally, PostgreSQL in Docker / production."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

log = logging.getLogger("chakravyuh.db")

url = settings.database_url
if url.startswith("postgres://"):            # Render / Heroku style URLs
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://") and "+psycopg" not in url:
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(timeout_s: float | None = None) -> None:
    """Create tables, waiting for the database to accept connections.

    PostgreSQL in Docker can report ready on its local socket while it is still initialising and
    refusing TCP connections, so a single attempt can fail at boot. Retry until DB_WAIT_SECONDS.
    """
    from . import models  # noqa: F401  (register tables)
    timeout_s = float(os.getenv("DB_WAIT_SECONDS", "90")) if timeout_s is None else timeout_s
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            Base.metadata.create_all(engine)
            if attempt > 1:
                log.info("database ready after %d attempts", attempt)
            return
        except OperationalError as e:
            if time.monotonic() >= deadline:
                log.error("database not reachable after %.0fs: %s", timeout_s, e.orig)
                raise
            log.warning("database not ready (attempt %d): %s", attempt, str(e.orig).splitlines()[0])
            time.sleep(2)
