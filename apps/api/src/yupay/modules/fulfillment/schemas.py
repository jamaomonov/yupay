"""Pydantic DTOs for the ``fulfillment`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CodeAccessIn(BaseModel):
    """Request a fresh magic link to view a guest order's delivered codes."""

    email: EmailStr


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


class FulfillmentTaskListItemOut(BaseModel):
    """A task as it appears in a list — everything except the attempt log.

    The log is unbounded: a task whose supplier order stays open polls its
    status once a minute for as long as that lasts, and one task in
    production carries 1641 attempts. A list showing only ``attempts_count``
    has no use for them, so they are fetched on demand from
    ``GET /admin/fulfillment/attempts?task_id=…`` instead of riding along with
    every row.
    """

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
    admin_note: str | None = None
    completed_by: str | None = None
    created_at: datetime
    succeeded_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None


class FulfillmentTaskListOut(BaseModel):
    items: list[FulfillmentTaskListItemOut]
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
    # Internal-only link to a screenshot / receipt PDF / chat transcript —
    # whatever the operator wants to keep as proof of fulfilment. Lands in
    # ``task.extra_metadata["proof_url"]`` and is **never** included in the
    # ``Delivery`` row, so the customer never sees it.
    proof_url: str | None = Field(default=None, max_length=2048)


class ManualFailIn(BaseModel):
    """Body of ``POST /admin/fulfillment/tasks/{id}/fail``."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=500)
    admin_note: str | None = Field(default=None, max_length=1000)


class BulkRetryIn(BaseModel):
    """Body of ``POST /admin/fulfillment/tasks/bulk-retry``.

    Cap is 100 — large bulks would hold the request-scoped transaction open while each
    task's saga step runs; a tighter limit forces the operator into reasonable batches.
    """

    model_config = ConfigDict(extra="forbid")

    task_ids: list[str] = Field(..., min_length=1, max_length=100)


class BulkRetrySkipped(BaseModel):
    """One task that bulk-retry decided not to replay."""

    model_config = ConfigDict(frozen=True)

    id: str
    reason: str


class BulkRetryOut(BaseModel):
    """Response of bulk-retry: the tasks we actually replayed plus skip diagnostics."""

    model_config = ConfigDict(frozen=True)

    retried: list[FulfillmentTaskOut]
    skipped: list[BulkRetrySkipped]


class AttemptAdminOut(BaseModel):
    """One row of the supplier-interaction audit feed for the admin UI."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    supplier: str
    kind: str
    status: str
    payload: dict[str, Any]
    error: str | None
    created_at: datetime


class AttemptAdminListOut(BaseModel):
    items: list[AttemptAdminOut]
    total: int = 0


__all__ = [
    "ArtifactKind",
    "AttemptAdminListOut",
    "AttemptAdminOut",
    "BulkRetryIn",
    "BulkRetryOut",
    "BulkRetrySkipped",
    "DeliveryChannel",
    "DeliveryListOut",
    "DeliveryOut",
    "FulfillmentAttemptOut",
    "FulfillmentTaskListItemOut",
    "FulfillmentTaskListOut",
    "FulfillmentTaskOut",
    "ManualCompleteIn",
    "ManualFailIn",
    "TaskStatus",
]
