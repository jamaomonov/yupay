"""Public and admin DTOs for the skins catalogue. Money is a string in transit."""

from __future__ import annotations

from datetime import datetime
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


class RarityFacetOut(FacetOut):
    color: str | None = None


class SkinFacetsOut(BaseModel):
    categories: list[FacetOut]
    weapons: list[FacetOut]
    exteriors: list[FacetOut]
    rarities: list[RarityFacetOut]
    #: An agent's side (``ct`` / ``t``); empty outside a category that has sides.
    teams: list[FacetOut] = []


class SkinSuggestOut(BaseModel):
    items: list[SkinItemOut]


class SkinListingSummaryOut(BaseModel):
    listing_id: int
    price_usd: str
    price_uzs: str | None


class SkinFamilyMemberOut(BaseModel):
    """Another wear (or StatTrak/Souvenir twin) of the same skin."""

    slug: str
    exterior: str | None
    stattrak: bool
    souvenir: bool
    price_usd: str | None
    price_uzs: str | None
    count: int


class SkinDetailOut(SkinItemOut):
    cheapest: list[SkinListingSummaryOut]
    family: list[SkinFamilyMemberOut]
    #: The SKU a storefront orders this item under (``cs2-skin``); ``None`` until it is
    #: seeded — the buy button stays hidden then.
    buy_sku_id: str | None = None


class SkinsPricingOut(BaseModel):
    """The rules document plus the flags that are env, not rules."""

    rules: PricingRules
    enabled: bool
    sync_enabled: bool
    categories: list[str]
    #: How many sellable skins a save reprices.
    items_active: int = 0
    #: When the five-minute price sync last wrote a price (``None`` before the first).
    prices_updated_at: datetime | None = None


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


class AdminSkinItemOut(BaseModel):
    """An item as the pricing screen needs it: what it costs, sells for, and its overrides."""

    slug: str
    name: str
    category: str
    weapon: str | None
    image_url: str | None
    count_auto: int
    cost_usd: str | None
    sell_price_usd: Decimal | None
    margin_override_pp: Decimal | None
    fixed_price_usd: Decimal | None


class AdminSkinItemsOut(BaseModel):
    """Search results (no total — the screen shows the first page only)."""

    items: list[AdminSkinItemOut]


class ResolveTradeIn(BaseModel):
    """What the operator did to settle a trade — optional, kept on the trade."""

    note: str | None = Field(default=None, max_length=500)
