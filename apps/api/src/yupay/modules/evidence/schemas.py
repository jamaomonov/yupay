"""Pydantic schemas for the ``evidence`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClientHints(BaseModel):
    """Passive signals a browser can report about itself.

    Every field is optional and every field is caller-supplied, so nothing here
    is proof on its own — it is corroboration, and it is bounded in length so a
    crafted payload cannot use the evidence table as storage. Deliberately no
    canvas/font/audio probing: those identify a device across sites, which is a
    different (and consent-bearing) activity from describing this one request.
    """

    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=32)
    screen: str | None = Field(default=None, max_length=32)


class OrderEvidenceOut(BaseModel):
    """Admin-only view of one order's capture. Never returned on public routes."""

    model_config = ConfigDict(from_attributes=True)

    order_id: str
    ip: str | None
    #: Cloudflare's edge-resolved two-letter country, or ``None``. A country
    #: code is not an address — it names a jurisdiction Cloudflare inferred,
    #: not a person, and it is absent on rows captured before this column
    #: existed.
    ip_country: str | None
    user_agent: str | None
    accept_language: str | None
    client_hints: dict[str, Any]
    created_at: datetime
    purge_after: datetime


class OrderEventOut(BaseModel):
    """One entry of the order's own timeline, replayed into the pack."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    actor: str | None
    created_at: datetime
    payload: dict[str, Any]


class EvidencePackOut(BaseModel):
    """What gets handed to the acquirer when a transaction is disputed.

    Shaped for that use: the capture, plus the order's full timeline, so the
    answer to "when was this delivered and to whom" is one request rather than
    an admin stitching screens together against a 5-day clock.
    """

    order_id: str
    status: str
    total_charged: str
    currency: str
    created_at: datetime
    paid_at: datetime | None
    delivered_at: datetime | None
    capture: OrderEvidenceOut | None
    timeline: list[OrderEventOut]


__all__ = ["ClientHints", "EvidencePackOut", "OrderEventOut", "OrderEvidenceOut"]
