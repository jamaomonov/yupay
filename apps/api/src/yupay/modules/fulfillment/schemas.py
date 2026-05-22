"""Pydantic DTOs for the ``fulfillment`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "in_progress", "succeeded", "failed", "cancelled"]
ArtifactKind = Literal["voucher_code", "topup_receipt", "license_key"]
DeliveryChannel = Literal["in_app", "email", "telegram"]


class DeliveryOut(BaseModel):
    """A delivery artifact as the customer sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    order_item_id: str
    channel: str
    artifact_kind: str
    artifact: dict[str, Any]
    delivered_at: datetime


class DeliveryListOut(BaseModel):
    items: list[DeliveryOut]


class FulfillmentAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    status: str
    payload: dict[str, Any]
    error: str | None
    created_at: datetime


class FulfillmentTaskOut(BaseModel):
    """Admin view of a task — includes attempts."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    order_item_id: str
    supplier: str
    status: TaskStatus
    attempts_count: int
    external_order_id: str | None
    last_error: str | None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    # Manual fulfilment audit (NULL for tasks completed by an upstream supplier).
    admin_note: str | None = None
    completed_by: str | None = None
    created_at: datetime
    succeeded_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    attempts: list[FulfillmentAttemptOut]


class FulfillmentTaskListOut(BaseModel):
    items: list[FulfillmentTaskOut]
    total: int = 0


class ManualCompleteIn(BaseModel):
    """Body of ``POST /admin/fulfillment/tasks/{id}/complete``."""

    model_config = ConfigDict(extra="forbid")

    artifact_kind: ArtifactKind
    # The artifact dict the customer sees on /orders/{id}/deliveries. Shape
    # depends on ``artifact_kind`` — see the frontend templates and the
    # MockFulfiller for reference (code/key/external_id+note).
    artifact: dict[str, Any] = Field(..., min_length=1)
    channel: DeliveryChannel = "in_app"
    admin_note: str | None = Field(default=None, max_length=1000)


class ManualFailIn(BaseModel):
    """Body of ``POST /admin/fulfillment/tasks/{id}/fail``."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=500)
    admin_note: str | None = Field(default=None, max_length=1000)


__all__ = [
    "ArtifactKind",
    "DeliveryChannel",
    "DeliveryListOut",
    "DeliveryOut",
    "FulfillmentAttemptOut",
    "FulfillmentTaskListOut",
    "FulfillmentTaskOut",
    "ManualCompleteIn",
    "ManualFailIn",
    "TaskStatus",
]
