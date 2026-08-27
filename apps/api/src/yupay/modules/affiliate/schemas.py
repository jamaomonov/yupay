"""Wire shapes for the buyer-facing affiliate endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from yupay.modules.affiliate.discount import DiscountRejection
from yupay.modules.orders.schemas import OrderItemIn


class PreviewIn(BaseModel):
    """A code and the cart it would apply to."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    currency: str = Field(min_length=3, max_length=8, default="USD")
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)


class PreviewOut(BaseModel):
    """Whether the code applies, and what it would do to the total.

    ``reason`` is only set when ``applicable`` is false, and it is deliberately
    coarse: a code that does not exist, one that is switched off, and one whose
    partner is suspended all report ``unknown``. Telling them apart would make
    this endpoint a lookup service for other people's promo codes.

    The amounts are for display. The order is priced again when it is actually
    created, so a code deactivated in between cannot be spent at the price
    shown here.
    """

    applicable: bool
    reason: DiscountRejection | None = None
    code: str | None = None
    percent: Decimal | None = None
    currency: str
    total_before: Decimal
    total_after: Decimal
    discount: Decimal


__all__ = ["PreviewIn", "PreviewOut"]
