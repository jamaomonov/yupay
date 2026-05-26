"""Pydantic DTOs for the integrations admin HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MappingKind = Literal["voucher", "game"]
CatalogKind = Literal["voucher", "game", "game_denom"]


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


__all__ = [
    "CatalogEntryOut",
    "CatalogKind",
    "CatalogListOut",
    "CatalogSyncOut",
    "MappingKind",
    "SupplierHealthOut",
    "SupplierMappingIn",
    "SupplierMappingListOut",
    "SupplierMappingOut",
]
