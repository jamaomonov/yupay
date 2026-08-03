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


class ProviderStatusOut(BaseModel):
    """A payment provider slug the storefront may show, and whether it's usable."""

    slug: str
    status: Literal["active", "maintenance"]


class ProvidersOut(BaseModel):
    providers: list[ProviderStatusOut]


class PaymentAdminListOut(BaseModel):
    items: list[PaymentAdminOut]
    total: int = 0


class SimulateWebhookIn(BaseModel):
    """Body of admin's ``POST /admin/payments/{id}/simulate-webhook``."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "failed", "cancelled"] = "succeeded"


class RefundIn(BaseModel):
    """Body of admin's ``POST /admin/payments/{id}/refund``."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = None
    reason: str | None = Field(default=None, max_length=500)


class PaymentWebhookOut(BaseModel):
    """One row of the webhook audit table."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    external_event_id: str
    received_at: datetime
    processed_at: datetime | None
    signature_ok: bool
    payload: dict[str, Any]


class PaymentWebhookListOut(BaseModel):
    items: list[PaymentWebhookOut]


class WebhookResolveIn(BaseModel):
    """Body of admin's ``POST /admin/webhooks/{id}/mark-resolved``."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class AdminProviderSummary(BaseModel):
    """One logical payment provider as the admin control panel sees it."""

    provider: str
    display_name: str
    slugs: list[str]
    config_available: bool
    state: Literal["active", "disabled", "maintenance"]
    changed_by: str | None
    changed_at: datetime | None


class AdminProviderListOut(BaseModel):
    providers: list[AdminProviderSummary]


class SetProviderStateIn(BaseModel):
    """Body of admin's ``PUT /admin/payments/providers/{provider}/state``."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["active", "disabled", "maintenance"]


class VolumeRow(BaseModel):
    """Payment volume for one currency within the analytics window."""

    model_config = ConfigDict(frozen=True)

    currency: str
    amount: Decimal
    count: int


class SuccessRateOut(BaseModel):
    """Succeeded / failed / pending counts + success percentage for the window.

    See ``provider_analytics`` module docstring for the exact status-bucket
    mapping (in particular how ``refunded``/``partially_refunded`` are
    treated as succeeded).
    """

    model_config = ConfigDict(frozen=True)

    succeeded: int
    failed: int
    pending: int
    success_pct: float


class RecentPaymentOut(BaseModel):
    """One payment row for the admin detail screen's recent list.

    Deliberately narrow — id/order_id/status/amount/currency/created_at only.
    Never include email/phone/user identifiers here (see AGENTS.md §9).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    order_id: str
    status: PaymentStatus
    amount: Decimal
    currency: str
    created_at: datetime


class ProviderIncidentsOut(BaseModel):
    """Stuck-pending + failed-webhook counts for a provider group.

    Mirrors ``admin.service.triage_payments``'s definitions exactly so the
    numbers agree with the existing triage screen.
    """

    model_config = ConfigDict(frozen=True)

    stuck_pending: int
    failed_webhooks: int


class AdminProviderDetailOut(BaseModel):
    """Full analytics detail for one logical payment provider (admin screen)."""

    model_config = ConfigDict(frozen=True)

    summary: AdminProviderSummary
    volume: list[VolumeRow] = Field(default_factory=list)
    success_rate: SuccessRateOut
    recent: list[RecentPaymentOut] = Field(default_factory=list)
    incidents: ProviderIncidentsOut


__all__ = [
    "AdminProviderDetailOut",
    "AdminProviderListOut",
    "AdminProviderSummary",
    "PaymentAdminListOut",
    "PaymentAdminOut",
    "PaymentAttemptOut",
    "PaymentIntentIn",
    "PaymentListOut",
    "PaymentOut",
    "PaymentStatus",
    "PaymentWebhookListOut",
    "PaymentWebhookOut",
    "ProviderIncidentsOut",
    "ProviderStatusOut",
    "ProvidersOut",
    "RecentPaymentOut",
    "RefundIn",
    "SetProviderStateIn",
    "SimulateWebhookIn",
    "SuccessRateOut",
    "VolumeRow",
    "WebhookResolveIn",
]
