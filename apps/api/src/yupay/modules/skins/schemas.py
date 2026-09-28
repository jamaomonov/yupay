"""Public and admin DTOs for the skins catalogue. Money is a string in transit."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from yupay.modules.skins.pricing import PricingRules


class SkinItemOut(BaseModel):
    slug: str
    name: str
    phase: str | None
    category: str
    weapon: str | None
    skin: str | None
    exterior: str | None
    stattrak: bool
    souvenir: bool
    rarity: str | None
    rarity_color: str | None
    image_url: str | None
    #: Our sell price for the cheapest auto listing; ``None`` when sold out.
    price_usd: str | None
    price_uzs: str | None
    steam_price_usd: str | None
    discount_percent: int | None
    count: int
    min_float: str | None
    max_float: str | None


class SkinsPageOut(BaseModel):
    items: list[SkinItemOut]
    next_cursor: str | None


class FacetOut(BaseModel):
    value: str
    count: int


class SkinFacetsOut(BaseModel):
    categories: list[FacetOut]
    weapons: list[FacetOut]
    exteriors: list[FacetOut]


class SkinSuggestOut(BaseModel):
    items: list[SkinItemOut]


class SkinListingSummaryOut(BaseModel):
    listing_id: int
    price_usd: str
    price_uzs: str | None


class SkinDetailOut(SkinItemOut):
    cheapest: list[SkinListingSummaryOut]


class SkinsPricingOut(BaseModel):
    """The rules document plus the flags that are env, not rules."""

    rules: PricingRules
    enabled: bool
    sync_enabled: bool
    categories: list[str]


class SkinQuoteOut(BaseModel):
    price_usd: str
    cost_usd: str
    expenses_usd: str
    bracket_margin_usd: str
    category_pp: str
    weapon_pp: str
    liquidity_pp: str
    item_pp: str
    effective_percent: str
    applied: str


class SkinItemPricingIn(BaseModel):
    """Per-item overrides; ``null`` clears one."""

    margin_override_pp: Decimal | None = Field(default=None, ge=-100, le=500, decimal_places=2)
    fixed_price_usd: Decimal | None = Field(default=None, ge=0, le=100000, decimal_places=2)


class SkinStickerOut(BaseModel):
    name: str
    image: str | None
    slot: int | None
    wear: float | None


class SkinListingOut(BaseModel):
    listing_id: int
    price_usd: str
    price_uzs: str | None
    float_value: float | None
    paint_seed: int | None
    stickers: list[SkinStickerOut]
    inspect_url: str | None


class SkinListingsOut(BaseModel):
    items: list[SkinListingOut]
    #: ``True`` when the answer is a stale cache or the snapshot, not a live read.
    degraded: bool
