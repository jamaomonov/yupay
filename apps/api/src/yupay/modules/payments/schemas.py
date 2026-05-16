"""Pydantic DTOs for the ``payments`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PaymentStatus = Literal[
    "pending",
    "requires_action",
    "succeeded",
    "failed",
    "cancelled",
    "refunded",
    "partially_refunded",
]


class PaymentIntentIn(BaseModel):
    """Body of ``POST /api/v1/payments/intents``."""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    provider: str = Field(min_length=2, max_length=32)
    return_url: str | None = Field(default=None, max_length=2048)


class PaymentOut(BaseModel):
    """A payment as the customer / admin sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    provider: str
    status: PaymentStatus
    amount: Decimal
    currency: str
    intent_url: str | None
    external_id: str | None
    created_at: datetime
    succeeded_at: datetime | None
    failed_at: datetime | None


class PaymentAttemptOut(BaseModel):
    """Single audit row exposed to admin."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    status: str
    payload: dict[str, Any]
    error: str | None
    created_at: datetime


class PaymentAdminOut(PaymentOut):
    """Admin-side detail with the full attempt log."""

    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    attempts: list[PaymentAttemptOut]


class PaymentListOut(BaseModel):
    items: list[PaymentOut]


class PaymentAdminListOut(BaseModel):
    items: list[PaymentAdminOut]


class SimulateWebhookIn(BaseModel):
    """Body of admin's ``POST /admin/payments/{id}/simulate-webhook``."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "failed", "cancelled"] = "succeeded"


__all__ = [
    "PaymentAdminListOut",
    "PaymentAdminOut",
    "PaymentAttemptOut",
    "PaymentIntentIn",
    "PaymentListOut",
    "PaymentOut",
    "PaymentStatus",
    "SimulateWebhookIn",
]
