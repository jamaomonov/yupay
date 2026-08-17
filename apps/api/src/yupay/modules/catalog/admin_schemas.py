"""Input/output DTOs for admin (write) catalog endpoints.

Public read schemas live in :mod:`yupay.modules.catalog.schemas`. Admin schemas are
intentionally separate so the public read surface stays small and renamings on the
admin side don't ripple into client code.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yupay.modules.catalog.image_url_safety import validate_optional_public_image_url
from yupay.modules.catalog.schemas import FormField

# Allow letters, digits, dashes; max 64 — matches column lengths and SEO conventions.
_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


def validate_form_fields(fields: list[FormField]) -> list[FormField]:
    """Reject a form schema whose player check can never succeed.

    ``check.server_field`` names the *sibling* whose value is sent as the
    checker's ``server_id`` — the storefront sends the checked field's own
    value as ``player_id`` and that sibling's as ``server_id``. Two ways to
    get this wrong produce a check that fails for every customer while looking
    configured:

    * pointing it at the checked field itself, which sends the server id as
      both halves (this shipped: ``mlbb-diamonds-ru`` carried the check on
      ``server`` with ``server_field: "server"``, so every Russian player's
      correct id was reported invalid);
    * pointing it at a key no field defines, which sends no server id at all.

    Neither is detectable at runtime — G2B simply answers "invalid", which the
    storefront honestly reports as the customer's mistake. So it has to be
    caught on write, which is where a hand edit in the admin introduces it.
    """
    keys = {f.key for f in fields}
    for f in fields:
        if f.check is None or f.check.server_field is None:
            continue
        target = f.check.server_field
        if target == f.key:
            raise ValueError(
                f"field '{f.key}': check.server_field points at the field itself; "
                "it must name the sibling field holding the server id"
            )
        if target not in keys:
            raise ValueError(
                f"field '{f.key}': check.server_field '{target}' is not a field on this product"
            )
    return fields


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
    # Short localized value-prop chips shown on the brand hero (e.g. "0%
    # комиссии", "Оплата в сумах"). Same precedent as ``instructions`` above:
    # only brands persist this; categories/products ignore it.
    highlights: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("highlights")
    @classmethod
    def _clean_highlights(cls, v: list[str]) -> list[str]:
        """Trim whitespace, drop empties, and cap each chip at 40 chars."""
        cleaned = [item.strip() for item in v]
        for item in cleaned:
            if len(item) > 40:
                raise ValueError("each highlight must be at most 40 characters")
        return [item for item in cleaned if item]


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

    # SSRF guard: Next's image optimizer fetches these server-side (see
    # apps/web/next.config.ts). Blank/omitted passes through untouched;
    # see yupay.modules.catalog.image_url_safety for what's blocked and the
    # documented residual risk (DNS rebinding).
    _validate_image_hosts = field_validator("logo_url", "hero_image_url")(
        validate_optional_public_image_url
    )


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

    # See BrandCreate — "" is the established "clear this field" convention
    # (admin_service.update_brand only skips ``None``), so it must keep
    # passing through unvalidated; validate_optional_public_image_url does
    # exactly that.
    _validate_image_hosts = field_validator("logo_url", "hero_image_url")(
        validate_optional_public_image_url
    )


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

    # SSRF guard — see BrandCreate._validate_image_hosts.
    _validate_image_hosts = field_validator("image_url")(validate_optional_public_image_url)
    _validate_form = field_validator("required_fields")(validate_form_fields)


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

    # SSRF guard — see BrandUpdate._validate_image_hosts.
    _validate_image_hosts = field_validator("image_url")(validate_optional_public_image_url)

    @field_validator("required_fields")
    @classmethod
    def _validate_form(cls, v: list[FormField] | None) -> list[FormField] | None:
        return None if v is None else validate_form_fields(v)


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
    # The margin price_usd is meant to hold above cost_usdt — see
    # ``Sku.margin_percent``. ``gt=-100`` mirrors
    # ``ck_skus_margin_percent_above_minus_100``: below that, the implied
    # price_usd hits zero or goes negative.
    margin_percent: Decimal | None = Field(default=None, gt=-100)
    # Variable-amount (Steam wallet-style) SKUs: the customer picks the
    # amount at checkout, so price_usd is a placeholder and these three
    # drive the actual price. See ``ck_skus_variable_amount_complete``.
    variable_amount: bool = False
    min_amount_usd: Decimal | None = Field(default=None, gt=0)
    max_amount_usd: Decimal | None = Field(default=None, gt=0)
    rate_multiplier: Decimal | None = Field(default=None, gt=0)
    # What the customer types, when it is not dollars: ("stars", 64.705882).
    # Both or neither — see ``ck_skus_amount_unit_complete``.
    amount_unit: str | None = Field(default=None, max_length=32)
    units_per_usd: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    active: bool = True
    price_overrides: list[SkuPriceOverrideIn] = Field(default_factory=list)

    # SSRF guard — see BrandCreate._validate_image_hosts.
    _validate_image_hosts = field_validator("image_url")(validate_optional_public_image_url)

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
    margin_percent: Decimal | None = Field(default=None, gt=-100)
    variable_amount: bool | None = None
    min_amount_usd: Decimal | None = Field(default=None, gt=0)
    max_amount_usd: Decimal | None = Field(default=None, gt=0)
    rate_multiplier: Decimal | None = Field(default=None, gt=0)
    # What the customer types, when it is not dollars: ("stars", 64.705882).
    # Both or neither — see ``ck_skus_amount_unit_complete``.
    amount_unit: str | None = Field(default=None, max_length=32)
    units_per_usd: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    price_overrides: list[SkuPriceOverrideIn] | None = None

    # SSRF guard — see BrandUpdate._validate_image_hosts.
    _validate_image_hosts = field_validator("image_url")(validate_optional_public_image_url)

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
    margin_percent: Decimal | None
    # Admin-only: never add these to the public SkuOut in schemas.py.
    # rate_multiplier especially — it's the margin (for variable-amount
    # SKUs; margin_percent above is the fixed-price equivalent).
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
