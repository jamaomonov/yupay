"""Pydantic DTOs for the integrations admin HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yupay.modules.catalog.schemas import FormField

MappingKind = Literal["voucher", "game"]
CatalogKind = Literal["voucher", "game", "game_denom"]

# Mirror catalog.admin_schemas._SLUG_PATTERN so a bad slug fails fast at import
# time with a clear 422 instead of deep inside create_brand/create_product.
_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


class SupplierMappingIn(BaseModel):
    """Payload for upserting a SKU↔supplier mapping."""

    model_config = ConfigDict(extra="forbid")

    supplier_slug: str = Field(min_length=2, max_length=32)
    kind: MappingKind
    external_product_id: str = Field(min_length=1, max_length=128)
    external_variant_id: str | None = Field(default=None, max_length=128)
    quantity: int = Field(default=1, ge=1, le=10_000)
    extra: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = Field(default=True)


class SupplierMappingOut(BaseModel):
    """Mapping row as exposed by admin endpoints."""

    model_config = ConfigDict(from_attributes=True)

    sku_id: str
    supplier_slug: str
    kind: MappingKind
    external_product_id: str
    external_variant_id: str | None
    quantity: int
    extra: dict[str, Any]
    is_active: bool
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class SupplierMappingListOut(BaseModel):
    items: list[SupplierMappingOut]


class PricePointOut(BaseModel):
    """One row in ``supplier_price_history`` as exposed to the admin UI."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sku_id: str
    supplier_slug: str
    kind: str
    external_product_id: str
    external_variant_id: str | None
    cost_usdt: str
    previous_cost_usdt: str | None
    source: str | None
    captured_at: datetime


class PriceHistoryOut(BaseModel):
    items: list[PricePointOut]


class PriceRefreshOut(BaseModel):
    """Result of a manual refresh-all-prices invocation."""

    checked: int
    moved: int
    alerts_sent: int
    errors: int


class CostSyncResult(BaseModel):
    """Outcome of the on-save cost refresh.

    Returned alongside the upsert response so the admin UI can flash
    either "cost updated from $X.XX → $Y.YY" or a clear reason when we
    couldn't pull a price (cache miss, unknown denom, etc).
    """

    updated: bool
    old_cost: str | None = None
    new_cost: str | None = None
    source: str | None = None
    reason: str | None = None


class SupplierMappingUpsertOut(BaseModel):
    """Combined upsert response: the row that was saved plus the optional
    cost-refresh outcome."""

    mapping: SupplierMappingOut
    cost_sync: CostSyncResult


class SupplierHealthOut(BaseModel):
    """Connectivity probe result for a supplier.

    ``available`` is the only required signal — everything else is best-effort
    and may be ``None`` when the supplier didn't answer or is not configured.
    """

    supplier: str
    available: bool
    reason: str | None = None
    balance: str | None = None
    currency: str | None = None
    username: str | None = None
    last_checked_at: datetime | None = None


class CatalogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supplier_slug: str
    kind: CatalogKind
    external_id: str
    title: str
    raw: dict[str, Any]
    fetched_at: datetime


class CatalogListOut(BaseModel):
    items: list[CatalogEntryOut]


class CatalogSyncOut(BaseModel):
    """Result of a one-shot catalog refresh for a supplier."""

    supplier: str
    vouchers_synced: int = 0
    games_synced: int = 0
    error: str | None = None


class GameDenomOut(BaseModel):
    """One catalogue (denomination) entry for a G2B game."""

    catalogue_name: str
    name: str
    amount: str | None = None
    price: str | None = None
    raw: dict[str, Any]


class GameDenomListOut(BaseModel):
    items: list[GameDenomOut]


class GameFieldsOut(BaseModel):
    """``POST /games/fields`` proxy result — which fields the customer must
    enter at checkout for this game."""

    fields: list[str]
    notes: str | None = None


class CheckPlayerIn(BaseModel):
    """Payload for the admin-triggered player verification probe."""

    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(min_length=1, max_length=64)
    server_id: str | None = Field(default=None, max_length=64)
    charname: str | None = Field(default=None, max_length=64)


class CheckPlayerOut(BaseModel):
    valid: bool
    name: str | None = None
    openid: str | None = None
    reason: str | None = None


class PlayerCheckIn(BaseModel):
    """Storefront player-verification request (no charname — it's a lookup)."""

    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(min_length=1, max_length=64)
    server_id: str | None = Field(default=None, max_length=64)


class PlayerCheckOut(BaseModel):
    """Storefront player-verification result.

    ``status`` discriminates three outcomes so the storefront can message each
    precisely:
      * ``valid``   — the id resolved; ``name`` is the account nickname.
      * ``invalid`` — the supplier answered but the id does not exist (the
        customer mistyped it). The storefront tells them the player isn't found.
      * ``error``   — a fault on our or the supplier's side (no mapping,
        unconfigured, upstream/network failure). The storefront shows a generic
        "couldn't check" and never blames the customer.

    ``openid`` is intentionally omitted — it's an internal G2B id and must not
    leak to the storefront.
    """

    status: Literal["valid", "invalid", "error"]
    name: str | None = None


class NewBrandIn(BaseModel):
    """New brand to create when importing a game (target='new_brand')."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG_PATTERN)
    category_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    logo_url: str | None = Field(default=None, max_length=1024)
    hero_image_url: str | None = Field(default=None, max_length=1024)
    accent_color: str | None = Field(default=None, max_length=16)


class ProductImportIn(BaseModel):
    """The game-as-product to create under the brand."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    required_fields: list[FormField] = Field(default_factory=list)
    image_url: str | None = Field(default=None, max_length=1024)


class DenomImportIn(BaseModel):
    """One supplier denomination to import as a SKU + mapping."""

    model_config = ConfigDict(extra="forbid")

    catalogue_name: str = Field(min_length=1, max_length=128)
    denomination: str = Field(min_length=1, max_length=64)
    sku_code: str = Field(min_length=1, max_length=64)
    cost_usdt: Decimal = Field(gt=0)
    price_usd_override: Decimal | None = Field(default=None, gt=0)
    region: str | None = Field(default=None, max_length=8)
    quantity: int = Field(default=1, ge=1, le=10_000)


class GameImportIn(BaseModel):
    """Payload for POST /admin/integrations/g2b/import."""

    model_config = ConfigDict(extra="forbid")

    game_code: str = Field(min_length=1, max_length=128)
    target: Literal["new_brand", "existing_brand"]
    brand_id: str | None = None
    new_brand: NewBrandIn | None = None
    product: ProductImportIn
    margin_percent: Decimal = Field(ge=0, le=1000)
    denominations: list[DenomImportIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_target(self) -> GameImportIn:
        if self.target == "new_brand" and self.new_brand is None:
            raise ValueError("new_brand is required when target='new_brand'")
        if self.target == "existing_brand" and not self.brand_id:
            raise ValueError("brand_id is required when target='existing_brand'")
        return self


class GameImportOut(BaseModel):
    """Result of a game import."""

    brand_id: str
    product_id: str
    created_skus: int
    created_mappings: int
    skipped: list[str]


__all__ = [
    "CatalogEntryOut",
    "CatalogKind",
    "CatalogListOut",
    "CatalogSyncOut",
    "CheckPlayerIn",
    "CheckPlayerOut",
    "CostSyncResult",
    "DenomImportIn",
    "GameDenomListOut",
    "GameDenomOut",
    "GameFieldsOut",
    "GameImportIn",
    "GameImportOut",
    "MappingKind",
    "NewBrandIn",
    "PlayerCheckIn",
    "PlayerCheckOut",
    "PriceHistoryOut",
    "PricePointOut",
    "PriceRefreshOut",
    "ProductImportIn",
    "SupplierHealthOut",
    "SupplierMappingIn",
    "SupplierMappingListOut",
    "SupplierMappingOut",
    "SupplierMappingUpsertOut",
]
