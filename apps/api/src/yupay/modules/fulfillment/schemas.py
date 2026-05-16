"""Pydantic DTOs for the ``fulfillment`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "in_progress", "succeeded", "failed", "cancelled"]


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
    created_at: datetime
    succeeded_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    attempts: list[FulfillmentAttemptOut]


class FulfillmentTaskListOut(BaseModel):
    items: list[FulfillmentTaskOut]


__all__ = [
    "DeliveryListOut",
    "DeliveryOut",
    "FulfillmentAttemptOut",
    "FulfillmentTaskListOut",
    "FulfillmentTaskOut",
    "TaskStatus",
]
