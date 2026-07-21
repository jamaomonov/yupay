"""Input/output DTOs for admin (write) catalog endpoints.

Public read schemas live in :mod:`yupay.modules.catalog.schemas`. Admin schemas are
intentionally separate so the public read surface stays small and renamings on the
admin side don't ripple into client code.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yupay.modules.catalog.schemas import FormField

# Allow letters, digits, dashes; max 64 — matches column lengths and SEO conventions.
_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


def require_variable_amount_fields(
    *,
    variable_amount: bool,
    min_amount_usd: Decimal | None,
    max_amount_usd: Decimal | None,
    rate_multiplier: Decimal | None,
) -> None:
    """Mirror the ``ck_skus_variable_amount_complete`` DB CHECK.

    The single source of truth for the invariant: when ``variable_amount`` is
    true, ``min_amount_usd``/``max_amount_usd``/``rate_multiplier`` must all be
    set with ``max_amount_usd >= min_amount_usd``. No-ops when
    ``variable_amount`` is false — callers decide separately whether to null
    the companions in that case.

    Raises a readable ``ValueError`` instead of letting an incomplete
    variable-amount SKU reach the DB and blow up as an opaque
    ``IntegrityError``. ``min_amount_usd > 0`` and ``rate_multiplier > 0`` are
    already enforced field-by-field via ``Field(gt=0)`` on the Pydantic
    models; this only checks presence and the min/max ordering, which need
    all three values at once.

    Called from two places against two different kinds of tuple:

    - The ``SkuCreate``/``SkuUpdate`` Pydantic ``model_validator``s, which can
      only see the request body — a ``ValueError`` here becomes part of
      Pydantic's own body-validation 422.
    - ``admin_service.update_sku``, against the row *after* merging a partial
      PATCH onto the existing SKU — the request body alone can't tell whether
      a partial edit (e.g. only ``max_amount_usd``) leaves an already-variable
      SKU complete or not, only the resolved row can. There the caller wraps
      the ``ValueError`` into ``core.errors.ValidationError``.
    """
    if not variable_amount:
        return
    missing = [
        name
        for name, value in (
            ("min_amount_usd", min_amount_usd),
            ("max_amount_usd", max_amount_usd),
            ("rate_multiplier", rate_multiplier),
        )
        if value is None
    ]
    if missing:
        raise ValueError("variable_amount SKUs require " + ", ".join(missing) + " to be set")
    # mypy: narrowed to non-None by the `missing` check above.
    assert min_amount_usd is not None
    assert max_amount_usd is not None
    if max_amount_usd < min_amount_usd:
        raise ValueError("max_amount_usd must be >= min_amount_usd")


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
    # Longform "how to top up / regions / where to find your ID" guide. Only
    # brands persist this; products ignore it.
    instructions: str | None = None


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
    maintenance: bool = False
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
    maintenance: bool | None = None
    translations: list[TranslationIn] | None = None


# ---------- brand FAQs ----------


class FaqTranslationIn(BaseModel):
    """One ``locale`` of a FAQ question/answer."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    locale: Literal["ru", "en", "uz"]
    question: str = Field(min_length=1, max_length=512)
    answer: str = Field(min_length=1)


class FaqCreate(BaseModel):
    """Body of ``POST /admin/catalog/brands/{brand_id}/faqs``. Brand comes from the path."""

    model_config = ConfigDict(extra="forbid")

    sort_order: int = 0
    active: bool = True
    translations: list[FaqTranslationIn] = Field(min_length=1)


class FaqUpdate(BaseModel):
    """Body of ``PATCH /admin/catalog/faqs/{id}``. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    sort_order: int | None = None
    active: bool | None = None
    translations: list[FaqTranslationIn] | None = None


class AdminFaqOut(BaseModel):
    """Admin-side FAQ view including inactive rows + per-locale translations."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    brand_id: str
    sort_order: int
    active: bool
    translations: list[FaqTranslationIn]


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
    # Variable-amount (Steam wallet-style) SKUs: the customer picks the
    # amount at checkout, so price_usd is a placeholder and these three
    # drive the actual price. See ``ck_skus_variable_amount_complete``.
    variable_amount: bool = False
    min_amount_usd: Decimal | None = Field(default=None, gt=0)
    max_amount_usd: Decimal | None = Field(default=None, gt=0)
    rate_multiplier: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    active: bool = True
    price_overrides: list[SkuPriceOverrideIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_variable_amount(self) -> SkuCreate:
        require_variable_amount_fields(
            variable_amount=self.variable_amount,
            min_amount_usd=self.min_amount_usd,
            max_amount_usd=self.max_amount_usd,
            rate_multiplier=self.rate_multiplier,
        )
        return self


class SkuUpdate(BaseModel):
    """Body of ``PATCH /admin/catalog/skus/{id}``.

    Most fields follow a "None means don't touch" convention. The
    variable-amount block is the exception: ``variable_amount``,
    ``min_amount_usd``, ``max_amount_usd`` and ``rate_multiplier`` are each
    applied independently in :func:`admin_service.update_sku` based on
    whether the caller actually sent them (``model_fields_set``), not on
    whether the value is ``None`` — sending one of the three amount fields
    as JSON ``null`` clears it, same as omitting it would leave it alone.
    This lets a partial edit like ``{"max_amount_usd": "1000"}`` against an
    already-variable SKU apply on its own, and lets the SKU edit form send
    ``variable_amount: false`` with the three fields as ``null`` to clear
    them. After merging, the *resulting* row is re-validated against
    ``ck_skus_variable_amount_complete`` (see
    :func:`require_variable_amount_fields`) — the request body alone can't
    tell whether a partial edit leaves an already-variable SKU complete.
    """

    model_config = ConfigDict(extra="forbid")

    sku_code: str | None = Field(default=None, max_length=64)
    denomination: str | None = None
    region: str | None = Field(default=None, max_length=8)
    price_usd: Decimal | None = Field(default=None, gt=0)
    cost_usdt: Decimal | None = Field(default=None, gt=0)
    variable_amount: bool | None = None
    min_amount_usd: Decimal | None = Field(default=None, gt=0)
    max_amount_usd: Decimal | None = Field(default=None, gt=0)
    rate_multiplier: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    price_overrides: list[SkuPriceOverrideIn] | None = None

    @model_validator(mode="after")
    def _validate_variable_amount(self) -> SkuUpdate:
        # `self.variable_amount` is `bool | None` here — `None` (not sent)
        # must skip the check, same as `False`, since a PATCH that never
        # mentions variable_amount isn't claiming to be a variable SKU.
        # This is a body-only check; the merged-row invariant for a partial
        # edit against an already-variable SKU is enforced in
        # admin_service.update_sku, which is the authority for that case.
        require_variable_amount_fields(
            variable_amount=bool(self.variable_amount),
            min_amount_usd=self.min_amount_usd,
            max_amount_usd=self.max_amount_usd,
            rate_multiplier=self.rate_multiplier,
        )
        return self


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
    maintenance: bool
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
    # Admin-only: never add these to the public SkuOut in schemas.py.
    # rate_multiplier especially — it's the margin.
    variable_amount: bool
    min_amount_usd: Decimal | None
    max_amount_usd: Decimal | None
    rate_multiplier: Decimal | None
    image_url: str | None
    sort_order: int
    active: bool
    price_overrides: list[SkuPriceOverrideIn]


class SkuPickerOut(BaseModel):
    """Compact SKU row tailored for the admin combobox.

    Includes the parent product's display name so the picker can render a
    self-explanatory row (``"PUBG Mobile · 60 UC"``) without a second
    fetch.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    product_name: str
    product_slug: str
    product_kind: str
    sku_code: str
    denomination: str | None
    region: str | None
    price_usd: Decimal
    active: bool


class BulkUzsPriceOut(BaseModel):
    """Result of ``POST /admin/catalog/skus/bulk-set-uzs-prices``."""

    model_config = ConfigDict(from_attributes=True)

    rate: Decimal
    fx_snapshot_id: str | None
    updated_total: int
    skipped_without_cost: int


__all__ = [
    "AdminBrandOut",
    "AdminCategoryOut",
    "AdminFaqOut",
    "AdminProductOut",
    "AdminSkuOut",
    "BrandCreate",
    "BrandUpdate",
    "BulkUzsPriceOut",
    "CategoryCreate",
    "CategoryTranslationIn",
    "CategoryUpdate",
    "FaqCreate",
    "FaqTranslationIn",
    "FaqUpdate",
    "ProductCreate",
    "ProductUpdate",
    "SkuCreate",
    "SkuPickerOut",
    "SkuPriceOverrideIn",
    "SkuUpdate",
    "TranslationIn",
    "require_variable_amount_fields",
]
