"""Pydantic schemas for the ``broadcasts`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MediaType = Literal["none", "photo", "video", "animation", "document"]
LocaleFilter = Literal["ru", "en", "uz"]
BroadcastStatus = Literal["draft", "scheduled", "sending", "sent", "failed", "canceled"]
RecipientStatus = Literal["pending", "sent", "failed", "blocked"]


class BroadcastCreateIn(BaseModel):
    """Body of admin's ``POST /admin/broadcasts``."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=500)
    body_html: str = Field(default="")
    media_type: MediaType = "none"
    media_url: str | None = Field(default=None, max_length=2048)
    locale_filter: LocaleFilter | None = None
    disable_web_page_preview: bool = True


class BroadcastUpdateIn(BroadcastCreateIn):
    """Body of admin's ``PUT /admin/broadcasts/{id}`` — same shape as create.

    Editing a draft resubmits the full form. If the target broadcast is currently
    ``scheduled``, ``service.update_draft`` resets it to ``draft`` and clears
    ``scheduled_at`` — an edited broadcast must be re-scheduled explicitly.
    """


class BroadcastOut(BaseModel):
    """Full admin view of a broadcast row: content + FSM state + delivery counters."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: BroadcastStatus
    body_html: str
    media_type: MediaType
    media_url: str | None
    media_file_id: str | None
    locale_filter: LocaleFilter | None
    disable_web_page_preview: bool
    scheduled_at: datetime | None
    total_recipients: int
    sent_count: int
    failed_count: int
    blocked_count: int
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class BroadcastListOut(BaseModel):
    """A page of :class:`BroadcastOut` plus the total matching count."""

    items: list[BroadcastOut]
    total: int


class RecipientOut(BaseModel):
    """One targeted recipient row.

    ``tg_chat_id`` is a Postgres ``bigint`` — serialized as a string (money-rule
    for big ids) so it survives round-tripping through a JS ``number`` without
    precision loss.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    tg_chat_id: str
    status: RecipientStatus
    error: str | None
    sent_at: datetime | None

    @field_validator("tg_chat_id", mode="before")
    @classmethod
    def _stringify_chat_id(cls, value: int | str) -> str:
        return str(value)


class RecipientListOut(BaseModel):
    """A page of :class:`RecipientOut` plus the total matching count."""

    items: list[RecipientOut]
    total: int


class ScheduleIn(BaseModel):
    """Body of admin's ``POST /admin/broadcasts/{id}/schedule``."""

    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime


class AudienceCountOut(BaseModel):
    """Response of the audience-size preview endpoint."""

    count: int


__all__ = [
    "AudienceCountOut",
    "BroadcastCreateIn",
    "BroadcastListOut",
    "BroadcastOut",
    "BroadcastStatus",
    "BroadcastUpdateIn",
    "LocaleFilter",
    "MediaType",
    "RecipientListOut",
    "RecipientOut",
    "RecipientStatus",
    "ScheduleIn",
]
