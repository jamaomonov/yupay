"""Pydantic DTOs for the ``catalog`` HTTP surface.

Storefront-facing — every payload is read-only, localised, and shaped to minimise
client round-trips. See ADR-0009 for the data model.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LocaleMap = dict[str, str]
"""Map of locale → translated string. Keys are locales we support (``ru``/``en``/``uz``)."""


class FormOption(BaseModel):
    """Single ``select`` option."""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: LocaleMap


class FieldCheck(BaseModel):
    """Opts a form field into storefront player verification.

    Present only on the player-id field. ``server_field`` names the sibling
    field whose value is passed as the checker's ``server_id``; set it when
    the product has a sibling server/zone field, leave unset otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["g2b", "waxpeer"]
    server_field: str | None = None


class FormField(BaseModel):
    """One field of a product's form schema."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: LocaleMap
    type: Literal["text", "email", "number", "select"]
    required: bool = True
    placeholder: LocaleMap | None = None
    help_text: LocaleMap | None = None
    pattern: str | None = None
    options: list[FormOption] | None = None
    check: FieldCheck | None = None


class PriceOut(BaseModel):
    """A price in one currency."""

    amount: Decimal
    currency: str
    source: Literal["usd", "override", "fx"] = "usd"


class CategoryOut(BaseModel):
    """A single category for the navigation tree."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    icon: str | None
    name: str
    description: str | None


class BrandOut(BaseModel):
    """A brand summary embedded inside product responses or shown on the brand list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    category_slug: str
    name: str
    short_description: str | None = None
    logo_url: str | None
    hero_image_url: str | None
    accent_color: str | None
    maintenance: bool = False


class SkuOut(BaseModel):
    """A single sellable variant."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sku_code: str
    denomination: str | None
    region: str | None
    image_url: str | None
    price_usd: Decimal
    variable_amount: bool = False
    min_amount_usd: Decimal | None = None
    max_amount_usd: Decimal | None = None
    display_price: PriceOut | None = Field(
        default=None,
        description="Localised price. Returned only when the request specifies a currency.",
    )


class ProductSummaryOut(BaseModel):
    """Compact product representation for product lists."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    brand_slug: str
    category_slug: str
    name: str
    short_description: str | None
    image_url: str | None
    kind: Literal["top_up", "voucher"]
    starting_price_usd: Decimal
    starting_display_price: PriceOut | None = None


class ProductDetailOut(BaseModel):
    """Full product page payload (with brand + form schema + SKUs)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    brand: BrandOut
    category_slug: str
    name: str
    short_description: str | None
    description: str | None
    image_url: str | None
    kind: Literal["top_up", "voucher"]
    required_fields: list[FormField]
    skus: list[SkuOut]


class FaqOut(BaseModel):
    """A localised FAQ entry shown on the brand page."""

    id: str
    question: str
    answer: str


class BrandDetailOut(BaseModel):
    """Full brand page payload: brand metadata + all its active products."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    category_slug: str
    name: str
    short_description: str | None
    description: str | None
    instructions: str | None = None
    logo_url: str | None
    hero_image_url: str | None
    accent_color: str | None
    maintenance: bool = False
    products: list[ProductSummaryOut]
    faqs: list[FaqOut] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class CategoryListOut(BaseModel):
    """Response for ``GET /catalog/categories``."""

    items: list[CategoryOut]


class BrandListOut(BaseModel):
    """Response for ``GET /catalog/brands``."""

    items: list[BrandOut]


class ProductListOut(BaseModel):
    """Response for ``GET /catalog/products``."""

    items: list[ProductSummaryOut]


__all__ = [
    "BrandDetailOut",
    "BrandListOut",
    "BrandOut",
    "CategoryListOut",
    "CategoryOut",
    "FieldCheck",
    "FormField",
    "FormOption",
    "LocaleMap",
    "PriceOut",
    "ProductDetailOut",
    "ProductListOut",
    "ProductSummaryOut",
    "SkuOut",
]
