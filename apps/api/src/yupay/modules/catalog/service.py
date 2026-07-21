"""Catalog read service.

All endpoints are read-only; the service shapes ORM rows into localised DTOs and applies
the price-resolution policy (override → FX → USD-only). See ADR-0009 for the model.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.modules.catalog.models import Brand, BrandFaq, Category, Product, Sku
from yupay.modules.catalog.schemas import (
    BrandDetailOut,
    BrandOut,
    CategoryOut,
    FaqOut,
    FormField,
    PriceOut,
    ProductDetailOut,
    ProductSummaryOut,
    SkuOut,
)
from yupay.modules.pricing.fx_guard import RateRejected, guarded_usd_rate
from yupay.modules.pricing.variable import display_rate, price_in_quote

if TYPE_CHECKING:
    from yupay.modules.fx.service import FxService

DEFAULT_LOCALE = "ru"


def _pick_translation(
    translations: list[Any],
    locale: str,
    *,
    fallback: str = DEFAULT_LOCALE,
) -> tuple[str, str | None, str | None, str | None]:
    """Return ``(name, short_description, description, instructions)`` for the locale.

    ``instructions`` only exists on brand translations; product translations
    return ``None`` for it (read via ``getattr``).
    """
    by_locale = {t.locale: t for t in translations}
    chosen = (
        by_locale.get(locale)
        or by_locale.get(fallback)
        or (translations[0] if translations else None)
    )
    if chosen is None:
        return ("", None, None, None)
    return (
        chosen.name,
        getattr(chosen, "short_description", None),
        getattr(chosen, "description", None),
        getattr(chosen, "instructions", None),
    )


def _pick_faq(
    translations: list[Any],
    locale: str,
    *,
    fallback: str = DEFAULT_LOCALE,
) -> tuple[str, str] | None:
    """Return ``(question, answer)`` for ``locale``/fallback, or None if untranslated."""
    by_locale = {t.locale: t for t in translations}
    chosen = (
        by_locale.get(locale)
        or by_locale.get(fallback)
        or (translations[0] if translations else None)
    )
    if chosen is None:
        return None
    return (chosen.question, chosen.answer)


def _pick_category_translation(translations: list[Any], locale: str) -> tuple[str, str | None]:
    by_locale = {t.locale: t for t in translations}
    chosen = (
        by_locale.get(locale)
        or by_locale.get(DEFAULT_LOCALE)
        or (translations[0] if translations else None)
    )
    if chosen is None:
        return ("", None)
    return chosen.name, chosen.description


def _brand_summary(brand: Brand, locale: str) -> BrandOut:
    name, short_desc, _, _ = _pick_translation(brand.translations, locale)
    return BrandOut(
        id=brand.id,
        slug=brand.slug,
        category_slug=brand.category.slug,
        name=name,
        short_description=short_desc,
        logo_url=brand.logo_url,
        hero_image_url=brand.hero_image_url,
        accent_color=brand.accent_color,
        maintenance=brand.maintenance,
    )


async def _resolve_variable_price(
    db: AsyncSession, sku: Sku, cu: str, *, rate_cache: dict[str, Decimal | None]
) -> PriceOut | None:
    """Display price for a variable-amount SKU: the guarded rate times the
    SKU's own margin multiplier, applied to one dollar — deliberately the
    per-dollar rate the storefront multiplies by the amount the customer
    enters, not ``price_usd``. ``price_usd`` on a variable SKU is only a
    positive placeholder required by the DB constraint; pricing (both this
    display price and checkout's :func:`orders.service._variable_line_charge`)
    never reads it for the amount charged, so it must not be read here
    either — otherwise an admin changing that placeholder would silently
    desync the displayed rate from what checkout actually charges. Returns
    ``None`` when the FX trust gate rejects the rate; never falls back to the
    raw market rate, since selling without margin is the loss the gate
    exists to prevent.

    ``rate_cache`` memoizes the guarded market rate per quote currency across
    every SKU resolved within one catalog request (product detail, brand
    detail, or listing) — mirroring the orders ``rate_cache`` in
    ``orders.service._variable_line_charge``. Without it, a product or
    listing page with several variable-amount SKUs would re-run the guarded
    rate check (each a handful of SQL statements) once per SKU. Both hits and
    rejections are cached: a currency present in the dict (even mapped to
    ``None``) is never re-queried within the same request.
    """
    if cu in rate_cache:
        market = rate_cache[cu]
    else:
        try:
            market = await guarded_usd_rate(db, quote=cu)
        except RateRejected:
            market = None
        rate_cache[cu] = market
    if market is None:
        return None
    rate = display_rate(market, sku.rate_multiplier or Decimal("1"))
    return PriceOut(amount=price_in_quote(Decimal("1"), rate=rate), currency=cu, source="fx")


async def _resolve_price(
    db: AsyncSession,
    sku: Sku,
    *,
    currency: str | None,
    fx: FxService | None,
    rate_cache: dict[str, Decimal | None],
) -> PriceOut | None:
    """Resolve the display price. Override → FX → ``None``. FX failures swallowed.

    Variable-amount SKUs (the customer picks the dollar amount at checkout —
    Steam wallet top-ups) go through :func:`_resolve_variable_price` instead:
    there's no SkuPrice override and no plain FX snapshot for them, only the
    guarded rate times the margin multiplier. They also have no margin-bearing
    USD price at all — checkout refuses to sell one in USD (see
    ``orders.service._resolve_line_unit_price``) — so USD (explicit or the
    default/no-currency case) resolves to ``None`` here too, the same
    "not sold this way" signal as a rejected rate, never face-value
    ``price_usd``.
    """
    if not currency:
        return None
    cu = currency.upper()

    if sku.variable_amount:
        if cu == "USD":
            return None
        return await _resolve_variable_price(db, sku, cu, rate_cache=rate_cache)

    if cu == "USD":
        return PriceOut(amount=sku.price_usd, currency="USD", source="usd")

    return await _resolve_fixed_price(sku, cu, fx)


async def _resolve_fixed_price(sku: Sku, cu: str, fx: FxService | None) -> PriceOut | None:
    """Override → FX → ``None``, for a fixed-price (non-variable-amount) SKU
    once ``currency`` is known to be non-USD. Split out of :func:`_resolve_price`
    to keep each branch's return-statement count small."""
    overrides = {o.currency.upper(): o for o in sku.price_overrides}
    explicit = overrides.get(cu)
    if explicit is not None:
        return PriceOut(amount=explicit.price, currency=cu, source="override")

    if fx is None:
        return None
    return await _resolve_fx_price(sku, cu, fx)


async def _resolve_fx_price(sku: Sku, cu: str, fx: FxService) -> PriceOut | None:
    """Plain FX conversion for a fixed-price SKU with no override. ``None``
    on any FX outage — swallowed, not surfaced, so the rest of the page still
    renders without a price for this one SKU."""
    from yupay.modules.fx.service import FxUnavailableError

    try:
        result = await fx.convert(sku.price_usd, base="USD", quote=cu)
    except FxUnavailableError:
        return None
    return PriceOut(amount=result.amount, currency=cu, source="fx")


def _build_product_summary(
    product: Product,
    *,
    locale: str,
    starting: Sku,
    display: PriceOut | None,
) -> ProductSummaryOut:
    name, short_desc, _, _ = _pick_translation(product.translations, locale)
    return ProductSummaryOut(
        id=product.id,
        slug=product.slug,
        brand_slug=product.brand.slug,
        category_slug=product.brand.category.slug,
        name=name,
        short_description=short_desc,
        image_url=product.image_url,
        kind=product.kind,  # type: ignore[arg-type]
        starting_price_usd=starting.price_usd,
        starting_display_price=display,
    )


async def list_categories(db: AsyncSession, *, locale: str) -> list[CategoryOut]:
    """Return all active categories with localised names."""
    stmt = (
        select(Category)
        .where(Category.active.is_(True))
        .order_by(Category.sort_order, Category.slug)
    )
    rows = (await db.execute(stmt)).scalars().all()

    result: list[CategoryOut] = []
    for row in rows:
        name, description = _pick_category_translation(row.translations, locale)
        result.append(
            CategoryOut(
                id=row.id,
                slug=row.slug,
                icon=row.icon,
                name=name,
                description=description,
            )
        )
    return result


async def list_brands(
    db: AsyncSession,
    *,
    locale: str,
    category_slug: str | None = None,
) -> list[BrandOut]:
    """Return active brands, optionally filtered by category slug."""
    stmt = (
        select(Brand)
        .options(selectinload(Brand.translations))
        .where(Brand.active.is_(True))
        .order_by(Brand.sort_order, Brand.slug)
    )
    if category_slug is not None:
        stmt = stmt.join(Brand.category).where(Category.slug == category_slug)

    rows = (await db.execute(stmt)).scalars().all()
    return [_brand_summary(b, locale) for b in rows]


async def get_brand_by_slug(
    db: AsyncSession,
    slug: str,
    *,
    locale: str,
    currency: str | None = None,
    fx: FxService | None = None,
) -> BrandDetailOut | None:
    """Return brand metadata + summaries of its active products."""
    stmt = (
        select(Brand)
        .options(
            selectinload(Brand.translations),
            selectinload(Brand.faqs).selectinload(BrandFaq.translations),
            selectinload(Brand.products).selectinload(Product.translations),
            selectinload(Brand.products)
            .selectinload(Product.skus)
            .selectinload(Sku.price_overrides),
        )
        .where(Brand.slug == slug, Brand.active.is_(True))
    )
    brand = (await db.execute(stmt)).scalar_one_or_none()
    if brand is None:
        return None

    name, short_desc, description, instructions = _pick_translation(brand.translations, locale)

    faqs_out: list[FaqOut] = []
    for faq in sorted((f for f in brand.faqs if f.active), key=lambda f: f.sort_order):
        picked = _pick_faq(faq.translations, locale)
        if picked is not None:
            faqs_out.append(FaqOut(id=faq.id, question=picked[0], answer=picked[1]))

    # Memoizes the guarded rate per currency across every product on this
    # brand page — see _resolve_variable_price.
    rate_cache: dict[str, Decimal | None] = {}
    products_out: list[ProductSummaryOut] = []
    for product in sorted((p for p in brand.products if p.active), key=lambda p: p.sort_order):
        active_skus = sorted(
            (s for s in product.skus if s.active),
            key=lambda s: (s.sort_order, s.price_usd),
        )
        if not active_skus:
            continue
        starting = active_skus[0]
        display = await _resolve_price(
            db, starting, currency=currency, fx=fx, rate_cache=rate_cache
        )
        products_out.append(
            _build_product_summary(product, locale=locale, starting=starting, display=display)
        )

    return BrandDetailOut(
        id=brand.id,
        slug=brand.slug,
        category_slug=brand.category.slug,
        name=name,
        short_description=short_desc,
        description=description,
        instructions=instructions,
        logo_url=brand.logo_url,
        hero_image_url=brand.hero_image_url,
        accent_color=brand.accent_color,
        maintenance=brand.maintenance,
        products=products_out,
        faqs=faqs_out,
    )


async def list_products(
    db: AsyncSession,
    *,
    locale: str,
    category_slug: str | None = None,
    brand_slug: str | None = None,
    currency: str | None = None,
    fx: FxService | None = None,
) -> list[ProductSummaryOut]:
    """List active products, optionally filtered by category and/or brand slug."""
    stmt = (
        select(Product)
        .options(
            selectinload(Product.skus).selectinload(Sku.price_overrides),
            selectinload(Product.translations),
        )
        .where(Product.active.is_(True))
        .order_by(Product.sort_order, Product.slug)
    )
    if brand_slug is not None:
        stmt = stmt.join(Product.brand).where(Brand.slug == brand_slug)
    elif category_slug is not None:
        stmt = stmt.join(Product.brand).join(Brand.category).where(Category.slug == category_slug)

    rows = (await db.execute(stmt)).scalars().all()

    # Memoizes the guarded rate per currency across every product in this
    # listing — see _resolve_variable_price.
    rate_cache: dict[str, Decimal | None] = {}
    summaries: list[ProductSummaryOut] = []
    for product in rows:
        active_skus = sorted(
            (s for s in product.skus if s.active),
            key=lambda s: (s.sort_order, s.price_usd),
        )
        if not active_skus:
            continue
        starting = active_skus[0]
        display = await _resolve_price(
            db, starting, currency=currency, fx=fx, rate_cache=rate_cache
        )
        summaries.append(
            _build_product_summary(product, locale=locale, starting=starting, display=display)
        )
    return summaries


async def get_product_by_slug(
    db: AsyncSession,
    slug: str,
    *,
    locale: str,
    currency: str | None = None,
    fx: FxService | None = None,
) -> ProductDetailOut | None:
    """Return a product detail (brand + form schema + SKUs) or ``None``."""
    # Join Brand and require it active too: a product under a hidden brand must
    # 404, not leak by direct slug. Without this a staged/disabled brand's
    # product is still reachable (and, for a variable-amount SKU, shows a price
    # it can't actually be bought at).
    stmt = (
        select(Product)
        .join(Brand, Brand.id == Product.brand_id)
        .options(
            selectinload(Product.skus).selectinload(Sku.price_overrides),
            selectinload(Product.translations),
        )
        .where(Product.slug == slug, Product.active.is_(True), Brand.active.is_(True))
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        return None

    name, short_desc, description, _ = _pick_translation(product.translations, locale)
    # Memoizes the guarded rate per currency across every SKU on this product
    # page — see _resolve_variable_price. This is the case the N+1 bites
    # hardest: a single product can list several variable-amount SKUs.
    rate_cache: dict[str, Decimal | None] = {}
    skus_out: list[SkuOut] = []
    for sku in sorted((s for s in product.skus if s.active), key=lambda s: s.sort_order):
        display = await _resolve_price(db, sku, currency=currency, fx=fx, rate_cache=rate_cache)
        skus_out.append(
            SkuOut(
                id=sku.id,
                sku_code=sku.sku_code,
                denomination=sku.denomination,
                region=sku.region,
                image_url=sku.image_url,
                price_usd=sku.price_usd,
                variable_amount=sku.variable_amount,
                min_amount_usd=sku.min_amount_usd,
                max_amount_usd=sku.max_amount_usd,
                display_price=display,
            )
        )

    return ProductDetailOut(
        id=product.id,
        slug=product.slug,
        brand=_brand_summary(product.brand, locale),
        category_slug=product.brand.category.slug,
        name=name,
        short_description=short_desc,
        description=description,
        image_url=product.image_url,
        kind=product.kind,  # type: ignore[arg-type]
        required_fields=[FormField.model_validate(f) for f in product.required_fields],
        skus=skus_out,
    )


async def get_sku_by_id(
    db: AsyncSession,
    sku_id: str,
    *,
    currency: str | None = None,
    fx: FxService | None = None,
) -> SkuOut | None:
    """Look up a single SKU. Used by checkout to verify the price."""
    stmt = (
        select(Sku)
        .options(selectinload(Sku.price_overrides))
        .where(Sku.id == sku_id, Sku.active.is_(True))
    )
    sku = (await db.execute(stmt)).scalar_one_or_none()
    if sku is None:
        return None
    display = await _resolve_price(db, sku, currency=currency, fx=fx, rate_cache={})
    return SkuOut(
        id=sku.id,
        sku_code=sku.sku_code,
        denomination=sku.denomination,
        region=sku.region,
        image_url=sku.image_url,
        price_usd=sku.price_usd,
        variable_amount=sku.variable_amount,
        min_amount_usd=sku.min_amount_usd,
        max_amount_usd=sku.max_amount_usd,
        display_price=display,
    )


__all__ = [
    "DEFAULT_LOCALE",
    "get_brand_by_slug",
    "get_product_by_slug",
    "get_sku_by_id",
    "list_brands",
    "list_categories",
    "list_products",
]
