"""Request / response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

EventType = Literal["MSG_RECV", "MSG_SENT", "CALL", "SCREEN_SHARE", "REMOTE_APP", "LINK_OPEN", "APK_INSTALL",
                    "UPI_OPEN", "PAYEE_NEW", "FD_BREAK", "PAY", "RECV"]


class ClientTags(BaseModel):
    """Tags computed on the phone by the Sentinel SLM (privacy mode: no raw text sent)."""
    tactics: list[str] = []
    p_scam: float = 0.0
    stage: str | None = None


class EventIn(BaseModel):
    type: EventType
    t: float | None = Field(None, description="seconds since session start; server time used if omitted")
    text: str | None = Field(None, max_length=2000)
    channel: str | None = None
    attrs: dict = {}
    client_tags: ClientTags | None = None


class SessionCreate(BaseModel):
    channel: str = "whatsapp"
    language: Literal["en", "hi", "hinglish"] = "en"
    source: Literal["live", "demo", "sim"] = "live"


class StepOut(BaseModel):
    p: float
    level: int
    escalated: bool = False
    action: str | None = None
    next_stage: str | None = None
    p_seq: float | None = None
    p_msg: float | None = None
    r_payee: float | None = None
    tactics: list[str] = []
    stage_guess: str | None = None


class AlertOut(BaseModel):
    id: str | None = None
    level: int
    action: str
    reason_code: str
    title: str
    message: str
    p: float
    response: str | None = None
    created_at: datetime | None = None


class ScoreOut(BaseModel):
    session_id: str | None = None
    mode: str
    latest: StepOut
    steps: list[StepOut]
    alert: AlertOut | None = None
    family_guess: str | None = None


class ScoreRequest(BaseModel):
    language: Literal["en", "hi", "hinglish"] = "en"
    channel: str = "whatsapp"
    events: list[EventIn]


class EventOut(BaseModel):
    idx: int
    t: float
    type: str
    text: str | None
    tactics: list[str]
    attrs: dict
    p: float
    level: int
    next_stage: str | None


class SessionOut(BaseModel):
    id: str
    source: str
    channel: str
    language: str
    status: str
    current_level: int
    max_p: float
    family_guess: str | None
    outcome: str | None
    created_at: datetime
    events: list[EventOut] = []
    alerts: list[AlertOut] = []


class AlertResponse(BaseModel):
    response: Literal["proceeded", "cancelled", "legit"]


class BetaSignup(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    org: str | None = None
    role: Literal["tester", "analyst"] = "tester"


class FeedbackIn(BaseModel):
    kind: Literal["general", "bug", "false_alert", "missed_scam"] = "general"
    rating: int | None = Field(None, ge=1, le=5)
    comment: str | None = Field(None, max_length=4000)
    page: str | None = None
    session_id: str | None = None
    alert_id: str | None = None


class CampaignPatch(BaseModel):
    status: Literal["new", "approved", "rejected"]


class SimulateRequest(BaseModel):
    n: int = Field(20, ge=1, le=500)
    families: list[str] | None = None
    scam_ratio: float = Field(0.5, ge=0, le=1)
    store: bool = True


class ArenaRequest(BaseModel):
    generations: int = Field(3, ge=1, le=8)
    population: int = Field(16, ge=4, le=60)
    per_genome: int = Field(2, ge=1, le=5)
    fresh: bool = True   # False continues the current arms race against the (possibly updated) defender
