"""Pydantic DTOs for the ``orders`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Imported from ``schemas`` rather than the module's ``api`` on purpose: ``api``
# pulls in ``routes``, and a schema module reaching for a router is how import
# cycles start. ``ClientHints`` is a leaf value object either way.
from yupay.modules.evidence.schemas import ClientHints

OrderStatus = Literal[
    "pending_payment",
    "paid",
    "fulfilling",
    "fulfilled",
    "delivered",
    "failed",
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
]


class OrderItemIn(BaseModel):
    """One line of a new-order request."""

    model_config = ConfigDict(extra="forbid")

    sku_id: str
    qty: int = Field(ge=1, le=100)
    fulfillment_data: dict[str, Any] = Field(default_factory=dict)
    # Set only for variable-amount SKUs (Steam wallet): how many dollars the
    # customer is buying. The price is derived from it server-side; the client
    # never sends a price.
    amount_usd: Decimal | None = Field(default=None, gt=0)


class OrderCreate(BaseModel):
    """Body of ``POST /api/v1/orders``."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=8, default="USD")
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)
    # Required for guest checkout; ignored when the caller is an authenticated user.
    guest_email: EmailStr | None = None
    # Passive browser signals kept for chargeback defence (ADR-0044). Optional
    # on purpose: a client that sends nothing still gets to buy, it just leaves
    # a thinner record behind.
    client_hints: ClientHints | None = None


class OrderItemDisplay(BaseModel):
    """What the customer/admin should see for this line.

    Resolved from the SKU → product → brand chain at read time, so a renamed
    product reflects in old orders too. For an at-purchase-time snapshot we'd
    move this to a stored jsonb column — deferred until we hit the use case.
    """

    model_config = ConfigDict(extra="forbid")

    brand_slug: str
    brand_name: str
    product_slug: str
    product_name: str
    product_kind: str  # "top_up" | "voucher"
    sku_code: str
    denomination: str | None
    region: str | None
    image_url: str | None
    # A variable-amount SKU's ``denomination`` is a generic label ("Любая
    # сумма"), not the amount the customer actually bought — the client needs
    # this flag to know when ``OrderItemOut.unit_price_usd`` (which for a
    # variable line *is* the chosen dollar amount, see
    # ``_resolve_line_unit_price``) is worth surfacing as "credited".
    variable_amount: bool


class OrderItemOut(BaseModel):
    """One line of an order response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sku_id: str
    qty: int
    unit_price_usd: Decimal
    fulfillment_state: str
    fulfillment_data: dict[str, Any]
    display: OrderItemDisplay | None = None


class OrderItemAdminOut(OrderItemOut):
    """Admin view of an order line — adds the internal supplier order id."""

    supplier_order_id: str | None = None


class OrderEventOut(BaseModel):
    """One audit row."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    payload: dict[str, Any]
    actor: str | None
    created_at: datetime


class OrderOut(BaseModel):
    """Full order response (matches list and detail)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: OrderStatus
    currency: str
    total_usd: Decimal
    total_charged: Decimal
    fx_snapshot_id: str | None
    expires_at: datetime
    created_at: datetime
    paid_at: datetime | None
    fulfilled_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    items: list[OrderItemOut]
    payment_provider: str | None = None


class OrderListOut(BaseModel):
    """Response for list endpoints."""

    items: list[OrderOut]


class OrderAdminOut(OrderOut):
    """Same as :class:`OrderOut` but exposes actor identifiers + audit trail."""

    items: list[OrderItemAdminOut]  # type: ignore[assignment]
    user_id: str | None
    # Plain ``str`` (not ``EmailStr``) on purpose: this is a read-only view of an
    # already-stored address, and re-validating it on output makes the whole
    # admin list 500 on a single odd row. Addresses that are legal to store but
    # rejected by strict RFC email validation — e.g. reserved-TLD test addresses
    # like ``uzum-test@test.local`` seeded during sandbox payment testing — must
    # still render. Email format is enforced at write time (``OrderCreate``).
    guest_email: str | None
    events: list[OrderEventOut]


class OrderFailIn(BaseModel):
    """Body for the admin "close this order as failed" action."""

    model_config = ConfigDict(extra="forbid")

    # Required and non-blank: the reason lands on the order timeline and is the
    # only record of why a paid order was closed without delivery.
    reason: str = Field(..., min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError("reason must be at least 3 non-blank characters")
        return cleaned


class OrderAdminListOut(BaseModel):
    items: list[OrderAdminOut]
    total: int = 0


class ClaimOut(BaseModel):
    """Response of ``POST /orders/claim`` — how many guest orders were migrated."""

    claimed: int


__all__ = [
    "ClaimOut",
    "OrderAdminListOut",
    "OrderAdminOut",
    "OrderCreate",
    "OrderEventOut",
    "OrderItemAdminOut",
    "OrderItemDisplay",
    "OrderItemIn",
    "OrderItemOut",
    "OrderListOut",
    "OrderOut",
    "OrderStatus",
]
