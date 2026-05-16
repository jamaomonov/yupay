"""HTTP routes for the ``catalog`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.catalog.deps import resolve_currency, resolve_locale
from yupay.modules.catalog.schemas import (
    BrandDetailOut,
    BrandListOut,
    CategoryListOut,
    ProductDetailOut,
    ProductListOut,
    SkuOut,
)
from yupay.modules.catalog.service import (
    get_brand_by_slug,
    get_product_by_slug,
    get_sku_by_id,
    list_brands,
    list_categories,
    list_products,
)
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.service import FxService, FxUnavailableError

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _fx_or_none(currency: str | None) -> FxService | None:
    """Build an FX service only when conversion is actually required."""
    if currency is None or currency.upper() == "USD":
        return None
    return build_default_service()


@router.get(
    "/categories",
    response_model=CategoryListOut,
    summary="List active categories",
)
async def get_categories(
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[str, Depends(resolve_locale)],
) -> CategoryListOut:
    """Localised category list for the storefront's navigation tree."""
    items = await list_categories(db, locale=locale)
    return CategoryListOut(items=items)


@router.get(
    "/brands",
    response_model=BrandListOut,
    summary="List brands, optionally filtered by category",
)
async def get_brands(
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[str, Depends(resolve_locale)],
    category: str | None = None,
) -> BrandListOut:
    """Brand index, optionally narrowed to one category."""
    items = await list_brands(db, locale=locale, category_slug=category)
    return BrandListOut(items=items)


@router.get(
    "/brands/{slug}",
    response_model=BrandDetailOut,
    summary="Brand detail (metadata + summaries of its products)",
)
async def get_brand(
    slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[str, Depends(resolve_locale)],
    currency: Annotated[str | None, Depends(resolve_currency)] = None,
) -> BrandDetailOut:
    """Brand page payload — used when a customer lands on /pubg-mobile."""
    fx = _fx_or_none(currency)
    try:
        brand = await get_brand_by_slug(db, slug, locale=locale, currency=currency, fx=fx)
    except FxUnavailableError:
        brand = await get_brand_by_slug(db, slug, locale=locale)
    if brand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")
    return brand


@router.get(
    "/products",
    response_model=ProductListOut,
    summary="List products, optionally filtered by category and/or brand",
)
async def get_products(
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[str, Depends(resolve_locale)],
    currency: Annotated[str | None, Depends(resolve_currency)] = None,
    category: str | None = None,
    brand: str | None = None,
) -> ProductListOut:
    """Localised product summaries with starting price."""
    fx = _fx_or_none(currency)
    try:
        items = await list_products(
            db,
            locale=locale,
            category_slug=category,
            brand_slug=brand,
            currency=currency,
            fx=fx,
        )
    except FxUnavailableError:
        items = await list_products(
            db, locale=locale, category_slug=category, brand_slug=brand
        )
    return ProductListOut(items=items)


@router.get(
    "/products/{slug}",
    response_model=ProductDetailOut,
    summary="Product detail (brand + form schema + SKUs)",
)
async def get_product(
    slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[str, Depends(resolve_locale)],
    currency: Annotated[str | None, Depends(resolve_currency)] = None,
) -> ProductDetailOut:
    """Full product page payload."""
    fx = _fx_or_none(currency)
    try:
        product = await get_product_by_slug(
            db, slug, locale=locale, currency=currency, fx=fx
        )
    except FxUnavailableError:
        product = await get_product_by_slug(db, slug, locale=locale)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="product not found")
    return product


@router.get(
    "/skus/{sku_id}",
    response_model=SkuOut,
    summary="Single SKU (used by checkout to verify prices)",
)
async def get_sku(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    currency: Annotated[str | None, Depends(resolve_currency)] = None,
) -> SkuOut:
    """Single SKU lookup."""
    fx = _fx_or_none(currency)
    try:
        sku = await get_sku_by_id(db, sku_id, currency=currency, fx=fx)
    except FxUnavailableError:
        sku = await get_sku_by_id(db, sku_id)
    if sku is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sku not found")
    return sku
