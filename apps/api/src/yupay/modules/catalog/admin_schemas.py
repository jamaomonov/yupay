"""Input/output DTOs for admin (write) catalog endpoints.

Public read schemas live in :mod:`yupay.modules.catalog.schemas`. Admin schemas are
intentionally separate so the public read surface stays small and renamings on the
admin side don't ripple into client code.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yupay.modules.catalog.schemas import FormField

# Allow letters, digits, dashes; max 64 — matches column lengths and SEO conventions.
_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


# ---------- translations (shared shape) ----------


class TranslationIn(BaseModel):
    """One ``locale`` of a translation. Used for categories, brands, and products."""

    # ``from_attributes`` lets ``AdminBrandOut.model_validate(ORM row)`` walk through
    # SQLAlchemy translation rows transparently.
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    locale: Literal["ru", "en", "uz"]
    name: str = Field(min_length=1, max_length=255)
    short_description: str | None = Field(default=None, max_length=512)
    description: str | None = None


class CategoryTranslationIn(BaseModel):
    """``categories`` has no ``short_description``, so it gets its own shape."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    locale: Literal["ru", "en", "uz"]
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


# ---------- categories ----------


class CategoryCreate(BaseModel):
    """Body of ``POST /admin/catalog/categories``."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG_PATTERN)
    icon: str | None = Field(default=None, max_length=64)
    sort_order: int = 0
    active: bool = True
    translations: list[CategoryTranslationIn] = Field(min_length=1)


class CategoryUpdate(BaseModel):
    """Body of ``PATCH /admin/catalog/categories/{id}``. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, pattern=_SLUG_PATTERN)
    icon: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    translations: list[CategoryTranslationIn] | None = None


# ---------- brands ----------


class BrandCreate(BaseModel):
    """Body of ``POST /admin/catalog/brands``."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG_PATTERN)
    category_id: str
    logo_url: str | None = Field(default=None, max_length=1024)
    hero_image_url: str | None = Field(default=None, max_length=1024)
    accent_color: str | None = Field(default=None, max_length=16)
    sort_order: int = 0
    active: bool = True
    translations: list[TranslationIn] = Field(min_length=1)


class BrandUpdate(BaseModel):
    """Body of ``PATCH /admin/catalog/brands/{id}``."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, pattern=_SLUG_PATTERN)
    category_id: str | None = None
    logo_url: str | None = None
    hero_image_url: str | None = None
    accent_color: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    translations: list[TranslationIn] | None = None


# ---------- products ----------


class ProductCreate(BaseModel):
    """Body of ``POST /admin/catalog/products``."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG_PATTERN)
    brand_id: str
    kind: Literal["top_up", "voucher"]
    supplier_hint: str | None = Field(default=None, max_length=64)
    image_url: str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    active: bool = True
    required_fields: list[FormField] = Field(default_factory=list)
    translations: list[TranslationIn] = Field(min_length=1)


class ProductUpdate(BaseModel):
    """Body of ``PATCH /admin/catalog/products/{id}``."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, pattern=_SLUG_PATTERN)
    brand_id: str | None = None
    kind: Literal["top_up", "voucher"] | None = None
    supplier_hint: str | None = None
    image_url: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    required_fields: list[FormField] | None = None
    translations: list[TranslationIn] | None = None


# ---------- SKUs ----------


class SkuPriceOverrideIn(BaseModel):
    """One row of ``sku_prices``."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    currency: str = Field(min_length=3, max_length=8)
    price: Decimal = Field(gt=0)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class SkuCreate(BaseModel):
    """Body of ``POST /admin/catalog/skus``."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    sku_code: str = Field(min_length=1, max_length=64)
    denomination: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=8)
    price_usd: Decimal = Field(gt=0)
    # Supplier wholesale cost in USDT (we pay vendors in USDT). Optional
    # so legacy SKUs can be edited before this field is filled in.
    cost_usdt: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    active: bool = True
    price_overrides: list[SkuPriceOverrideIn] = Field(default_factory=list)


class SkuUpdate(BaseModel):
    """Body of ``PATCH /admin/catalog/skus/{id}``."""

    model_config = ConfigDict(extra="forbid")

    sku_code: str | None = Field(default=None, max_length=64)
    denomination: str | None = None
    region: str | None = Field(default=None, max_length=8)
    price_usd: Decimal | None = Field(default=None, gt=0)
    cost_usdt: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    price_overrides: list[SkuPriceOverrideIn] | None = None


# ---------- admin read DTOs ----------


class AdminCategoryOut(BaseModel):
    """Admin-side category view including inactive rows + per-locale translations."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    icon: str | None
    sort_order: int
    active: bool
    translations: list[CategoryTranslationIn]


class AdminBrandOut(BaseModel):
    """Admin-side brand view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    category_id: str
    logo_url: str | None
    hero_image_url: str | None
    accent_color: str | None
    sort_order: int
    active: bool
    translations: list[TranslationIn]


class AdminProductOut(BaseModel):
    """Admin-side product view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    brand_id: str
    kind: Literal["top_up", "voucher"]
    supplier_hint: str | None
    image_url: str | None
    sort_order: int
    active: bool
    required_fields: list[FormField]
    translations: list[TranslationIn]


class AdminSkuOut(BaseModel):
    """Admin-side SKU view including overrides."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    sku_code: str
    denomination: str | None
    region: str | None
    price_usd: Decimal
    cost_usdt: Decimal | None
    image_url: str | None
    sort_order: int
    active: bool
    price_overrides: list[SkuPriceOverrideIn]


__all__ = [
    "AdminBrandOut",
    "AdminCategoryOut",
    "AdminProductOut",
    "AdminSkuOut",
    "BrandCreate",
    "BrandUpdate",
    "CategoryCreate",
    "CategoryTranslationIn",
    "CategoryUpdate",
    "ProductCreate",
    "ProductUpdate",
    "SkuCreate",
    "SkuPriceOverrideIn",
    "SkuUpdate",
    "TranslationIn",
]
