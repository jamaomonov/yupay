"""Pydantic DTOs for the ``orders`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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


class OrderCreate(BaseModel):
    """Body of ``POST /api/v1/orders``."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=8, default="USD")
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)
    # Required for guest checkout; ignored when the caller is an authenticated user.
    guest_email: EmailStr | None = None


class OrderItemOut(BaseModel):
    """One line of an order response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sku_id: str
    qty: int
    unit_price_usd: Decimal
    fulfillment_state: str
    fulfillment_data: dict[str, Any]
    supplier_order_id: str | None


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


class OrderListOut(BaseModel):
    """Response for list endpoints."""

    items: list[OrderOut]


class OrderAdminOut(OrderOut):
    """Same as :class:`OrderOut` but exposes actor identifiers + audit trail."""

    user_id: str | None
    guest_email: EmailStr | None
    events: list[OrderEventOut]


class OrderAdminListOut(BaseModel):
    items: list[OrderAdminOut]


__all__ = [
    "OrderAdminListOut",
    "OrderAdminOut",
    "OrderCreate",
    "OrderEventOut",
    "OrderItemIn",
    "OrderItemOut",
    "OrderListOut",
    "OrderOut",
    "OrderStatus",
]
