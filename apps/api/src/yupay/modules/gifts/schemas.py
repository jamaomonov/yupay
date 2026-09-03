"""Pydantic DTOs for the ``gifts`` admin and public HTTP surfaces.

Public catalog DTOs (``GiftAppOut`` and friends) carry money as ``str``, not
``Decimal`` — same convention as the rest of the public wire format (see
AGENTS.md §9: minor-unit money is a string in transit). ``price_usd`` is our
2-dp sell price after margin; ``price_uzs`` is a whole-UZS display string,
``None`` when FX was unavailable for this request.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class GiftsAdminSettingsOut(BaseModel):
    """Current Steam Gifts settings, as shown on the admin settings page."""

    margin_percent: Decimal
    enabled: bool
    region_default: str
    regions: list[str]


class GiftsSettingsIn(BaseModel):
    """Admin edit of the margin percent.

    Bounded at the edge as well as in the column (``Numeric(10, 4)``,
    ``CHECK margin_percent >= 0``): 0-100 is the only range that makes sense
    for a percentage margin, and an unbounded ``Decimal`` would otherwise
    reach Postgres as a 500 rather than a 422 — same reasoning as
    ``fx.schemas.RateSettingIn.manual_rate``.
    """

    margin_percent: Decimal = Field(ge=0, le=100, max_digits=10, decimal_places=4)


class GiftAppOut(BaseModel):
    """One catalog row — a listing item, a DLC entry, or the top of a detail
    payload; all three share this shape upstream."""

    app_id: int
    name: str
    image: str | None
    type: str
    price_usd: str | None
    price_uzs: str | None
    discount_percent: int | None
    packages_count: int
    dlc_count: int


class GiftsListOut(BaseModel):
    """A page of :class:`GiftAppOut` rows plus the upstream total."""

    items: list[GiftAppOut]
    total: int


class GiftZonePriceOut(BaseModel):
    """Our sell price for one package, in one offered zone."""

    zone: str
    price_usd: str
    price_uzs: str | None


class GiftPackageOut(BaseModel):
    """One purchasable edition of a gift app, priced per offered zone."""

    id: int
    name: str
    image: str | None
    discount_percent: int | None
    prices: list[GiftZonePriceOut]


class GiftAppDetailOut(GiftAppOut):
    """Full app card: everything on :class:`GiftAppOut`, plus packages/DLC."""

    description: str | None
    packages: list[GiftPackageOut]
    dlc_total: int
    zones: list[str]
    zone_default: str


__all__ = [
    "GiftAppDetailOut",
    "GiftAppOut",
    "GiftPackageOut",
    "GiftZonePriceOut",
    "GiftsAdminSettingsOut",
    "GiftsListOut",
    "GiftsSettingsIn",
]
