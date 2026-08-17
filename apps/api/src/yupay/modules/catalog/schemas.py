"""Pydantic DTOs for the ``catalog`` HTTP surface.

Storefront-facing — every payload is read-only, localised, and shaped to minimise
client round-trips. See ADR-0009 for the data model.

``FormField`` doubles as the *write*-time shape too: ``catalog/admin_schemas.py``
imports it directly for product create/update payloads, so validators declared
here (e.g. :func:`_assert_pattern_is_safe`) run for admin writes as well as for
serialising stored data back out.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LocaleMap = dict[str, str]
"""Map of locale → translated string. Keys are locales we support (``ru``/``en``/``uz``)."""

# ``FormField.pattern`` is admin-authored and later run inline, synchronously,
# against untrusted customer input via ``re.fullmatch`` in
# ``yupay.modules.orders.validation`` — with no timeout. A pathological pattern
# (catastrophic backtracking) would block the whole event loop. This is a
# pragmatic — not exhaustive — guard applied at write time: a length cap, a
# ceiling on bounded repetitions, and a heuristic for the classic
# nested-quantifier shapes (``(a+)+``, ``(a*)*``, ``(a+)*``, ...). It does not
# catch every ReDoS-prone construct (e.g. alternation-based blowups like
# ``(a|a)+``); the checkout side additionally caps the input length before
# matching (see ``orders/validation.py``) as defense in depth.
_PATTERN_MAX_LENGTH = 200
_PATTERN_MAX_QUANTIFIERS = 20
_PATTERN_MAX_BOUNDED_REPEAT = 1000

_QUANTIFIER = r"(?:[*+]|\{\d+,?\d*\})"
_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*" + _QUANTIFIER + r"[^()]*\)" + _QUANTIFIER)
_QUANTIFIER_RE = re.compile(_QUANTIFIER)
_BOUNDED_REPEAT_RE = re.compile(r"\{(\d+)(?:,(\d+))?\}")


def _assert_pattern_is_safe(pattern: str) -> None:
    """Raise ``ValueError`` if ``pattern`` looks ReDoS-prone.

    Called from :class:`FormField`'s validator, so it runs for every
    admin-submitted ``pattern`` (product create/update) as well as when
    re-hydrating stored patterns.
    """
    if len(pattern) > _PATTERN_MAX_LENGTH:
        raise ValueError(f"pattern is too long (max {_PATTERN_MAX_LENGTH} chars)")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"pattern is not a valid regular expression: {exc}") from exc
    if _NESTED_QUANTIFIER_RE.search(pattern):
        raise ValueError(
            "pattern contains a nested quantifier (e.g. '(a+)+'), which risks "
            "catastrophic backtracking"
        )
    for match in _BOUNDED_REPEAT_RE.finditer(pattern):
        for bound in match.groups():
            if bound and int(bound) > _PATTERN_MAX_BOUNDED_REPEAT:
                raise ValueError(
                    f"pattern has a bounded repetition above {_PATTERN_MAX_BOUNDED_REPEAT}"
                )
    if len(_QUANTIFIER_RE.findall(pattern)) > _PATTERN_MAX_QUANTIFIERS:
        raise ValueError(f"pattern has more than {_PATTERN_MAX_QUANTIFIERS} quantifiers")


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

    @field_validator("pattern")
    @classmethod
    def _pattern_is_safe(cls, v: str | None) -> str | None:
        if v is not None:
            _assert_pattern_is_safe(v)
        return v


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


class BrandRatingOut(BaseModel):
    """Aggregate customer rating for a brand (omitted when there are no reviews)."""

    avg: float
    count: int


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
    rating: BrandRatingOut | None = None


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
    # Present when the amount is typed in something other than dollars — the
    # storefront labels the field with `amount_unit` and converts the USD
    # bounds with `units_per_usd`. Absent means dollars, as Steam has always
    # been, so an older client keeps working unchanged.
    amount_unit: str | None = None
    units_per_usd: Decimal | None = None
    # Boolean, never the count. How many codes a supplier is holding is not the
    # customer's business: the number moves without warning as other resellers
    # draw on the same pool, so "3 left" is a promise we cannot keep. Defaults
    # to True so an older client that does not know the field still sells.
    in_stock: bool = Field(
        default=True,
        description="False when the supplier has no codes left. The count itself is not exposed.",
    )
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
    rating: BrandRatingOut | None = None


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
