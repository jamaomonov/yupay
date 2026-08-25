"""DTOs for admin-wide cross-cutting endpoints (search, customer-overview, …).

These schemas are intentionally generic: a single :class:`SearchHit` shape lets the admin SPA
render every result group with the same component while keeping per-type metadata in the
``sublabel`` field. See ADR-0017.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yupay.modules.users.schemas import UserAdminOut

HitType = Literal["user", "order", "payment", "sku"]


class SearchHit(BaseModel):
    """One row in the search palette."""

    model_config = ConfigDict(frozen=True)

    type: HitType
    id: str
    label: str
    sublabel: str | None = None
    # Structured status/amount so the admin SPA can render them through its own
    # localizer + currency-aware money formatter instead of a pre-baked English
    # string (round-2 fix — see AGENTS.md). ``sublabel`` keeps whatever doesn't
    # fit those two buckets (provider, tg handle, external id, …).
    status: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    # Admin SPA deep-link path. Sprint-0 points users to ``/users/{id}``; once Customer 360
    # ships (Sprint 1) it will point to ``/customers/{id}``.
    path: str


class SearchOut(BaseModel):
    """Grouped search results — one bucket per source."""

    model_config = ConfigDict(frozen=True)

    users: list[SearchHit] = Field(default_factory=list)
    orders: list[SearchHit] = Field(default_factory=list)
    payments: list[SearchHit] = Field(default_factory=list)
    skus: list[SearchHit] = Field(default_factory=list)


# ---------- Customer 360 overview ----------

# Risk flag identifiers. The UI is free to render them however it likes; the backend
# never returns a localized string here so the admin SPA owns the message catalog.
RiskFlag = Literal[
    "no_email",
    "no_telegram",
    "fresh_account",
    "many_failed_payments",
]


class CustomerOrderSummary(BaseModel):
    """Compact order row for the customer-360 list. Full detail lives at /orders/{id}."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    status: str
    currency: str
    total_charged: Decimal
    items_count: int
    created_at: datetime
    delivered_at: datetime | None


class CustomerPaymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    order_id: str
    provider: str
    status: str
    amount: Decimal
    currency: str
    external_id: str | None
    created_at: datetime


class CustomerTaskSummary(BaseModel):
    """Open fulfilment task (pending / in_progress / failed) for this customer."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    order_id: str
    supplier: str
    status: str
    last_error: str | None
    created_at: datetime


class CustomerBalanceOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    kind: str
    currency: str
    balance: Decimal


class CustomerStatsOut(BaseModel):
    """Aggregate counters for the customer header card."""

    model_config = ConfigDict(frozen=True)

    total_orders: int
    delivered_orders: int
    total_spent_usd: Decimal
    failed_payments: int


class CustomerOverviewOut(BaseModel):
    """Aggregated read-only view of a customer for the admin SPA's /customers/{id} page."""

    model_config = ConfigDict(frozen=True)

    user: UserAdminOut
    stats: CustomerStatsOut
    recent_orders: list[CustomerOrderSummary] = Field(default_factory=list)
    recent_payments: list[CustomerPaymentSummary] = Field(default_factory=list)
    open_fulfillment_tasks: list[CustomerTaskSummary] = Field(default_factory=list)
    wallet_balances: list[CustomerBalanceOut] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)


# ---------- Payments Triage ----------


class PaymentTriageRow(BaseModel):
    """One stuck-pending payment row for the triage screen."""

    model_config = ConfigDict(frozen=True)

    id: str
    order_id: str
    user_id: str | None
    guest_email: str | None
    provider: str
    status: str
    amount: Decimal
    currency: str
    created_at: datetime
    waiting_minutes: int


class WebhookTriageRow(BaseModel):
    """One failed-webhook row for the triage screen."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    provider: str
    external_event_id: str
    received_at: datetime
    processed_at: datetime | None
    signature_ok: bool


class PaymentTriageOut(BaseModel):
    """Aggregate response for /admin/payments/triage."""

    model_config = ConfigDict(frozen=True)

    threshold_minutes: int
    stuck_pending: list[PaymentTriageRow] = Field(default_factory=list)
    failed_webhooks: list[WebhookTriageRow] = Field(default_factory=list)


# ---------- Saved segments ----------


class SavedSegmentIn(BaseModel):
    """Body of ``POST /admin/segments`` — create a bookmark."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=80)]
    # Restrict to admin-SPA-internal routes — saved segments are bookmarks for the
    # operator's own tool, not a generic link sink. Any starting with ``/``,
    # without protocol, is fair game.
    path: Annotated[str, Field(min_length=1, max_length=255)]
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _path_must_be_internal(cls, value: str) -> str:
        v = value.strip()
        if not v.startswith("/") or v.startswith("//") or "://" in v:
            raise ValueError("path must be an internal admin-SPA route starting with /")
        return v


class SavedSegmentOut(BaseModel):
    """One saved segment as returned to its owning admin."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    name: str
    path: str
    params: dict[str, Any]
    created_at: datetime


class SavedSegmentListOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SavedSegmentOut]


__all__ = [
    "CustomerBalanceOut",
    "CustomerOrderSummary",
    "CustomerOverviewOut",
    "CustomerPaymentSummary",
    "CustomerStatsOut",
    "CustomerTaskSummary",
    "HitType",
    "PaymentTriageOut",
    "PaymentTriageRow",
    "RiskFlag",
    "SavedSegmentIn",
    "SavedSegmentListOut",
    "SavedSegmentOut",
    "SearchHit",
    "SearchOut",
    "WebhookTriageRow",
]


class UserRefOut(BaseModel):
    """Just enough to draw a person: a face and a name.

    The panel linked to profiles by raw UUID in seven places. An id says
    nothing an operator can recognise, and every one of those call sites would
    otherwise have to grow its own join.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    #: Display name, falling back to the login email — whichever the account has.
    name: str | None
    photo_url: str | None


class OrderRefOut(BaseModel):
    """Just enough to recognise an order: what was in it.

    The first line's artwork, because that is what an operator remembers about
    an order — not its id. An order with no items (a wallet deposit) has no
    image and says so by omission.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    image_url: str | None
    #: "Free Fire · 110 Diamonds" — the same label the orders list prints.
    label: str | None


class AdminRefsOut(BaseModel):
    """Batched display data for ids a page already holds.

    One request per page instead of a join on every endpoint that happens to
    carry a user or order id.
    """

    model_config = ConfigDict(extra="forbid")

    users: list[UserRefOut] = []
    orders: list[OrderRefOut] = []
