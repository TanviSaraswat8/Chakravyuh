"""Database tables."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return uuid.uuid4().hex[:16]


class BetaTester(Base):
    __tablename__ = "beta_testers"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    org: Mapped[str | None] = mapped_column(String(160), nullable=True)
    role: Mapped[str] = mapped_column(String(40), default="tester")      # tester | analyst | admin
    cohort: Mapped[str] = mapped_column(String(20), default="alpha")     # alpha | beta
    api_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: "ck_" + secrets.token_hex(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ScamSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_id)
    tester_id: Mapped[str | None] = mapped_column(ForeignKey("beta_testers.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="live")       # live | demo | sim
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    language: Mapped[str] = mapped_column(String(12), default="en")
    status: Mapped[str] = mapped_column(String(20), default="open")       # open | closed
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    max_p: Mapped[float] = mapped_column(Float, default=0.0)
    family_guess: Mapped[str | None] = mapped_column(String(40), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)   # paid | cancelled | legit
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    events: Mapped[list[Event]] = relationship(back_populates="session", order_by="Event.idx",
                                                 cascade="all, delete-orphan")
    alerts: Mapped[list[Alert]] = relationship(back_populates="session", order_by="Alert.created_at",
                                                 cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    t: Mapped[float] = mapped_column(Float, default=0.0)
    type: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tactics: Mapped[list] = mapped_column(JSON, default=list)
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)
    p: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    next_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ScamSession] = relationship(back_populates="events")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    event_idx: Mapped[int] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    reason_code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(12), default="en")
    p: Mapped[float] = mapped_column(Float, default=0.0)
    response: Mapped[str | None] = mapped_column(String(20), nullable=True)   # proceeded | cancelled | legit
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ScamSession] = relationship(back_populates="alerts")


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tester_id: Mapped[str | None] = mapped_column(ForeignKey("beta_testers.id"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alert_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    page: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)      # 1..5
    kind: Mapped[str] = mapped_column(String(20), default="general")      # general | bug | false_alert | missed_scam
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="new")        # new | approved | rejected
    card: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
