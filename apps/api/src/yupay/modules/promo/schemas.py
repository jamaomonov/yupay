"""Pydantic schemas for the ``promo`` module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PromoRedeemIn(BaseModel):
    """Body of ``POST /promo/redeem``."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=64)


class PromoRedeemOut(BaseModel):
    """What a successful (or replayed) redemption returns."""

    code: str
    amount: Decimal
    currency: str


class PromoCreateIn(BaseModel):
    """Body of admin's ``POST /admin/promo``."""

    model_config = ConfigDict(extra="forbid")

    # Omitted ⇒ the service generates an opaque one.
    code: str | None = Field(default=None, min_length=3, max_length=64)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    max_redemptions: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None


class PromoAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    amount: Decimal
    currency: str
    max_redemptions: int | None
    redemptions: int
    active: bool
    expires_at: datetime | None
    created_at: datetime


class PromoRedemptionOut(BaseModel):
    """One redemption, shaped for the admin's "кто активировал" list.

    Carries the identity fields the operator recognises a person by — avatar,
    name, Telegram handle — so the list is scannable without opening each
    profile. ``user_id`` is what the row links to.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    display_name: str | None = None
    photo_url: str | None = None
    tg_username: str | None = None
    email: str | None = None
    redeemed_at: datetime


class PromoRedemptionListOut(BaseModel):
    items: list[PromoRedemptionOut]
    total: int = 0


class PromoAdminListOut(BaseModel):
    items: list[PromoAdminOut]


__all__ = [
    "PromoAdminListOut",
    "PromoAdminOut",
    "PromoCreateIn",
    "PromoRedeemIn",
    "PromoRedeemOut",
    "PromoRedemptionListOut",
    "PromoRedemptionOut",
]
