"""Pydantic DTOs for the audit feed."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# Source tables that feed the timeline. Adding a new event surface means
# adding it both here and in service._fetch_<source>.
AuditSource = Literal[
    "order_event",
    "payment_attempt",
    "payment_webhook",
    "fulfillment_attempt",
    "wallet_transaction",
]


class AuditEventOut(BaseModel):
    """One row of the unified audit feed."""

    model_config = ConfigDict(extra="forbid")

    id: str
    ts: datetime
    source: AuditSource
    kind: str
    actor: str | None
    target_id: str | None
    target_kind: str | None
    payload: dict[str, Any]


class AuditListOut(BaseModel):
    items: list[AuditEventOut]


__all__ = ["AuditEventOut", "AuditListOut", "AuditSource"]
