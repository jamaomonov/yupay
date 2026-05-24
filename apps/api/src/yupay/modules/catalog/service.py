"""Catalog read service.

All endpoints are read-only; the service shapes ORM rows into localised DTOs and applies
the price-resolution policy (override → FX → USD-only). See ADR-0009 for the model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.catalog.schemas import (
    BrandDetailOut,
    BrandOut,
    CategoryOut,
    FormField,
    PriceOut,
    ProductDetailOut,
    ProductSummaryOut,
    SkuOut,
)

if TYPE_CHECKING:
    from yupay.modules.fx.service import FxService

DEFAULT_LOCALE = "ru"


def _pick_translation(
    translations: list[Any],
    locale: str,
    *,
    fallback: str = DEFAULT_LOCALE,
) -> tuple[str, str | None, str | None]:
    """Return ``(name, short_description, description)`` for ``locale`` or fallback."""
    by_locale = {t.locale: t for t in translations}
    chosen = (
        by_locale.get(locale)
        or by_locale.get(fallback)
        or (translations[0] if translations else None)
    )
    if chosen is None:
        return ("", None, None)
    return (
        chosen.name,
        getattr(chosen, "short_description", None),
        getattr(chosen, "description", None),
    )


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
    name, short_desc, _ = _pick_translation(brand.translations, locale)
    return BrandOut(
        id=brand.id,
        slug=brand.slug,
        category_slug=brand.category.slug,
        name=name,
        short_description=short_desc,
        logo_url=brand.logo_url,
        hero_image_url=brand.hero_image_url,
        accent_color=brand.accent_color,
    )


async def _resolve_price(
    sku: Sku,
    *,
    currency: str | None,
    fx: FxService | None,
) -> PriceOut | None:
    """Resolve the display price. Override → FX → ``None``. FX failures swallowed."""
    if not currency:
        return None
    cu = currency.upper()
    if cu == "USD":
        return PriceOut(amount=sku.price_usd, currency="USD", source="usd")

    overrides = {o.currency.upper(): o for o in sku.price_overrides}
    explicit = overrides.get(cu)
    if explicit is not None:
        return PriceOut(amount=explicit.price, currency=cu, source="override")

    if fx is None:
        return None
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
    name, short_desc, _ = _pick_translation(product.translations, locale)
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

    name, short_desc, description = _pick_translation(brand.translations, locale)
    products_out: list[ProductSummaryOut] = []
    for product in sorted((p for p in brand.products if p.active), key=lambda p: p.sort_order):
        active_skus = sorted(
            (s for s in product.skus if s.active),
            key=lambda s: (s.sort_order, s.price_usd),
        )
        if not active_skus:
            continue
        starting = active_skus[0]
        display = await _resolve_price(starting, currency=currency, fx=fx)
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
        logo_url=brand.logo_url,
        hero_image_url=brand.hero_image_url,
        accent_color=brand.accent_color,
        products=products_out,
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

    summaries: list[ProductSummaryOut] = []
    for product in rows:
        active_skus = sorted(
            (s for s in product.skus if s.active),
            key=lambda s: (s.sort_order, s.price_usd),
        )
        if not active_skus:
            continue
        starting = active_skus[0]
        display = await _resolve_price(starting, currency=currency, fx=fx)
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
    stmt = (
        select(Product)
        .options(
            selectinload(Product.skus).selectinload(Sku.price_overrides),
            selectinload(Product.translations),
        )
        .where(Product.slug == slug, Product.active.is_(True))
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        return None

    name, short_desc, description = _pick_translation(product.translations, locale)
    skus_out: list[SkuOut] = []
    for sku in sorted((s for s in product.skus if s.active), key=lambda s: s.sort_order):
        display = await _resolve_price(sku, currency=currency, fx=fx)
        skus_out.append(
            SkuOut(
                id=sku.id,
                sku_code=sku.sku_code,
                denomination=sku.denomination,
                region=sku.region,
                image_url=sku.image_url,
                price_usd=sku.price_usd,
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
    display = await _resolve_price(sku, currency=currency, fx=fx)
    return SkuOut(
        id=sku.id,
        sku_code=sku.sku_code,
        denomination=sku.denomination,
        region=sku.region,
        image_url=sku.image_url,
        price_usd=sku.price_usd,
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
