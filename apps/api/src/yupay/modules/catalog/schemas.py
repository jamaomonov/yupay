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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from yupay.core.logging import get_logger

log = get_logger("yupay.catalog.schemas")

LocaleMap = dict[str, str]
"""Map of locale → translated string. Keys are locales we support (``ru``/``en``/``uz``)."""

_LENIENT_HELP_IMAGES_KEY = "lenient_help_images"

HELP_IMAGES_READ_CONTEXT: dict[str, bool] = {_LENIENT_HELP_IMAGES_KEY: True}
"""Pass as ``context=`` to ``model_validate`` on a *read* path that re-hydrates an
already-stored ``FormField``/``required_fields`` row — ``catalog.service`` for the
storefront, ``AdminProductOut`` for the admin list/create/update responses.

Opts into dropping a ``help_images`` entry that no longer validates (see
``FormField._drop_nonconforming_help_images_on_read``) instead of failing the whole
field. Omit it — the default for ``ProductCreate``/``ProductUpdate`` request bodies,
which FastAPI parses with no context, and for any bare ``FormField(...)``/
``HelpImage(...)`` construction — to keep the strict raise an admin write relies on
for its 422.
"""

# ``FormField.help_images`` cap — an instruction longer than this has stopped
# being an instruction. Enforced here (the model both admin writes and
# storefront reads flow through) rather than only at the HTTP layer, so it
# holds for every caller, not just the admin endpoint.
_MAX_HELP_IMAGES = 6

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


class HelpImage(BaseModel):
    """One annotated screenshot in a field's "Где найти?" walkthrough.

    Order matters: the list order **is** the walkthrough ("open the
    profile screen" -> "the ID sits under the nickname"), so it is
    preserved exactly as submitted — never re-sorted when serialising back
    out.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    caption: LocaleMap | None = None

    @field_validator("url")
    @classmethod
    def _url_is_own_media(cls, v: str) -> str:
        """Refuse anything but our own R2 media bucket.

        Without this, a field's help becomes an arbitrary remote-image
        embed: an operator account could point it at any third-party host,
        which is both a privacy leak (every storefront visitor's IP
        reaching that host) and an availability risk. Single source of
        truth for "one of our own uploaded media URLs" is
        ``storage.service.is_own_media_url`` — also re-exported from
        ``storage.api`` for any caller that wants the module's public
        surface — reused here rather than re-deriving the
        ``r2_public_base_url`` prefix.

        Imported lazily, and from ``storage.service`` rather than
        ``storage.api``: ``storage.api`` also re-exports the presign
        router, which imports ``admin.api`` -> ``auth.deps`` ->
        ``api.v1.deps`` -> (Python must init the ``api.v1`` package first)
        ``api.v1.__init__``, which imports ``admin.api`` again while it is
        still mid-import — a circular import that only surfaces when
        something reaches ``admin.api`` *before* ``api.v1`` has been
        touched at all, which is exactly what constructing a bare
        ``FormField`` in a unit test (no app bootstrap) does.
        ``storage.service`` has none of that: it only depends on
        ``core.config``/``core.errors``/``core.ids``/``storage.client``.

        The lazy import stays for now; the real fix is upstream of this file.
        ``auth.deps`` reaches into ``api.v1.deps`` only for ``db_session`` —
        which is *defined* there, wrapping ``core.db.get_session``, not
        re-exported from ``core.db`` — and that reach-in is what forces
        ``api.v1``'s package ``__init__`` to run before ``admin.api`` has
        finished importing. Moving ``db_session`` (and ``SessionDep``) into
        ``core.db`` and having ``api.v1.deps`` re-export them, so
        ``auth.deps`` imports ``db_session`` from ``core.db`` instead, would
        break the cycle at its root; swapping which module ``auth.deps``
        imports it *from* today would just fail, since ``core.db`` doesn't
        define that name yet.
        """
        from yupay.modules.storage.service import is_own_media_url

        if not is_own_media_url(v):
            raise ValueError("help_images url must point at our own media bucket")
        return v


class FormField(BaseModel):
    """One field of a product's form schema."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: LocaleMap
    type: Literal["text", "email", "number", "select"]
    required: bool = True
    placeholder: LocaleMap | None = None
    help_text: LocaleMap | None = None
    help_images: list[HelpImage] | None = None
    pattern: str | None = None
    options: list[FormOption] | None = None
    check: FieldCheck | None = None

    @field_validator("pattern")
    @classmethod
    def _pattern_is_safe(cls, v: str | None) -> str | None:
        if v is not None:
            _assert_pattern_is_safe(v)
        return v

    @field_validator("help_images", mode="before")
    @classmethod
    def _drop_nonconforming_help_images_on_read(cls, v: object, info: ValidationInfo) -> object:
        """On an opted-in read, drop a ``help_images`` entry that fails ``HelpImage``
        validation instead of failing the whole field.

        ``HelpImage._url_is_own_media`` is the one validator here whose verdict
        depends on mutable runtime config (``settings.r2_public_base_url``), not
        only on the stored value — flip that config (an environment cutover, a
        prod-dump restore into staging) and every previously-valid stored URL
        becomes invalid at once. ``catalog.service.get_product_by_slug`` and
        ``AdminProductOut`` both call ``model_validate`` for *every* stored field
        on *every* read, so letting that raise would 500 the storefront product
        page — and the admin page an operator would use to fix it.

        Runs ``mode="before"`` (raw dicts, ahead of Pydantic's own list-item
        coercion) so a dropped entry never reaches — and never itself raises
        through — the list. Reuses ``HelpImage.model_validate`` per item rather
        than re-deriving what "conforming" means, so this can't drift out of
        sync with what ``HelpImage``'s own validators actually enforce.

        Only runs when the caller opts in via ``context=HELP_IMAGES_READ_CONTEXT``
        (the storefront and admin *read* paths). Write bodies
        (``ProductCreate``/``ProductUpdate``, parsed by FastAPI with no context)
        and any bare construction keep the strict per-item 422 from
        ``HelpImage._url_is_own_media`` — an operator gets a clear error and can
        act, which a silently dropped image would deny them.
        """
        if not isinstance(v, list) or not (info.context or {}).get(_LENIENT_HELP_IMAGES_KEY):
            return v
        kept: list[object] = []
        for item in v:
            try:
                HelpImage.model_validate(item, context=info.context)
            except ValidationError as exc:
                url = item.get("url") if isinstance(item, dict) else None
                log.warning(
                    "catalog.help_images.dropped_on_read",
                    field_key=info.data.get("key"),
                    url=url,
                    reason=str(exc),
                )
                continue
            kept.append(item)
        return kept

    @field_validator("help_images")
    @classmethod
    def _help_images_bounded(cls, v: list[HelpImage] | None) -> list[HelpImage] | None:
        if v is not None and len(v) > _MAX_HELP_IMAGES:
            raise ValueError(f"help_images accepts at most {_MAX_HELP_IMAGES} images")
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
    # On a package: how many units it delivers, so the storefront can price a
    # typed amount from whichever package it falls in. On the variable line and
    # on anything not sold by unit: absent.
    units: int | None = None
    # Admin-configured quantity bounds for a unit SKU (Telegram Stars): the
    # customer types how many of `amount_unit` to buy, and the storefront
    # clamps the input to [min_qty, max_qty]. Both absent means this SKU isn't
    # sold by typed quantity — an older client that doesn't know the fields
    # simply never sees them, same precedent as `amount_unit` above.
    min_qty: int | None = None
    max_qty: int | None = None
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
    "HELP_IMAGES_READ_CONTEXT",
    "BrandDetailOut",
    "BrandListOut",
    "BrandOut",
    "CategoryListOut",
    "CategoryOut",
    "FieldCheck",
    "FormField",
    "FormOption",
    "HelpImage",
    "LocaleMap",
    "PriceOut",
    "ProductDetailOut",
    "ProductListOut",
    "ProductSummaryOut",
    "SkuOut",
]
