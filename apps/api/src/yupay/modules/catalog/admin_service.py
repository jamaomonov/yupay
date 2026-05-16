"""Write-side service for admin catalog endpoints.

Public read service lives in :mod:`yupay.modules.catalog.service`. The split keeps the
admin surface auditable in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
    SkuPrice,
)

if TYPE_CHECKING:
    from yupay.modules.catalog.admin_schemas import (
        BrandCreate,
        BrandUpdate,
        CategoryCreate,
        CategoryUpdate,
        ProductCreate,
        ProductUpdate,
        SkuCreate,
        SkuUpdate,
    )


# ---------- categories ----------


async def list_all_categories(db: AsyncSession) -> list[Category]:
    """All categories, active or not. Admin-side."""
    stmt = (
        select(Category)
        .options(selectinload(Category.translations))
        .order_by(Category.sort_order, Category.slug)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_category(db: AsyncSession, category_id: str) -> Category:
    stmt = (
        select(Category)
        .options(selectinload(Category.translations))
        .where(Category.id == category_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("category not found")
    return row


async def create_category(db: AsyncSession, body: CategoryCreate) -> Category:
    row = Category(
        id=new_id(),
        slug=body.slug,
        icon=body.icon,
        sort_order=body.sort_order,
        active=body.active,
        translations=[
            CategoryTranslation(locale=t.locale, name=t.name, description=t.description)
            for t in body.translations
        ],
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists") from exc
    return row


async def update_category(
    db: AsyncSession, category_id: str, body: CategoryUpdate
) -> Category:
    row = await get_category(db, category_id)
    if body.slug is not None:
        row.slug = body.slug
    if body.icon is not None:
        row.icon = body.icon
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    if body.active is not None:
        row.active = body.active
    if body.translations is not None:
        row.translations = [
            CategoryTranslation(locale=t.locale, name=t.name, description=t.description)
            for t in body.translations
        ]
    row.updated_at = now()
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists") from exc
    return row


async def delete_category(db: AsyncSession, category_id: str) -> None:
    row = await get_category(db, category_id)
    await db.delete(row)
    await db.flush()


# ---------- brands ----------


async def list_all_brands(db: AsyncSession) -> list[Brand]:
    stmt = (
        select(Brand)
        .options(selectinload(Brand.translations))
        .order_by(Brand.sort_order, Brand.slug)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_brand(db: AsyncSession, brand_id: str) -> Brand:
    stmt = (
        select(Brand)
        .options(selectinload(Brand.translations))
        .where(Brand.id == brand_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("brand not found")
    return row


async def create_brand(db: AsyncSession, body: BrandCreate) -> Brand:
    # Validate the referenced category exists.
    await get_category(db, body.category_id)
    row = Brand(
        id=new_id(),
        slug=body.slug,
        category_id=body.category_id,
        logo_url=body.logo_url,
        hero_image_url=body.hero_image_url,
        accent_color=body.accent_color,
        sort_order=body.sort_order,
        active=body.active,
        translations=[
            BrandTranslation(
                locale=t.locale,
                name=t.name,
                short_description=t.short_description,
                description=t.description,
            )
            for t in body.translations
        ],
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists") from exc
    return row


async def update_brand(db: AsyncSession, brand_id: str, body: BrandUpdate) -> Brand:
    row = await get_brand(db, brand_id)
    if body.category_id is not None:
        await get_category(db, body.category_id)
        row.category_id = body.category_id
    for attr in ("slug", "logo_url", "hero_image_url", "accent_color", "sort_order", "active"):
        value = getattr(body, attr)
        if value is not None:
            setattr(row, attr, value)
    if body.translations is not None:
        row.translations = [
            BrandTranslation(
                locale=t.locale,
                name=t.name,
                short_description=t.short_description,
                description=t.description,
            )
            for t in body.translations
        ]
    row.updated_at = now()
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists") from exc
    return row


async def delete_brand(db: AsyncSession, brand_id: str) -> None:
    row = await get_brand(db, brand_id)
    await db.delete(row)
    await db.flush()


# ---------- products ----------


async def list_all_products(
    db: AsyncSession, *, brand_id: str | None = None
) -> list[Product]:
    stmt = (
        select(Product)
        .options(selectinload(Product.translations))
        .order_by(Product.sort_order, Product.slug)
    )
    if brand_id is not None:
        stmt = stmt.where(Product.brand_id == brand_id)
    return list((await db.execute(stmt)).scalars().all())


async def get_product(db: AsyncSession, product_id: str) -> Product:
    stmt = (
        select(Product)
        .options(selectinload(Product.translations))
        .where(Product.id == product_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("product not found")
    return row


async def create_product(db: AsyncSession, body: ProductCreate) -> Product:
    await get_brand(db, body.brand_id)
    row = Product(
        id=new_id(),
        slug=body.slug,
        brand_id=body.brand_id,
        kind=body.kind,
        supplier_hint=body.supplier_hint,
        image_url=body.image_url,
        sort_order=body.sort_order,
        active=body.active,
        required_fields=[f.model_dump(mode="json") for f in body.required_fields],
        translations=[
            ProductTranslation(
                locale=t.locale,
                name=t.name,
                short_description=t.short_description,
                description=t.description,
            )
            for t in body.translations
        ],
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists") from exc
    return row


async def update_product(
    db: AsyncSession, product_id: str, body: ProductUpdate
) -> Product:
    row = await get_product(db, product_id)
    if body.brand_id is not None:
        await get_brand(db, body.brand_id)
        row.brand_id = body.brand_id
    for attr in ("slug", "kind", "supplier_hint", "image_url", "sort_order", "active"):
        value = getattr(body, attr)
        if value is not None:
            setattr(row, attr, value)
    if body.required_fields is not None:
        row.required_fields = [f.model_dump(mode="json") for f in body.required_fields]
    if body.translations is not None:
        row.translations = [
            ProductTranslation(
                locale=t.locale,
                name=t.name,
                short_description=t.short_description,
                description=t.description,
            )
            for t in body.translations
        ]
    row.updated_at = now()
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists") from exc
    return row


async def delete_product(db: AsyncSession, product_id: str) -> None:
    row = await get_product(db, product_id)
    await db.delete(row)
    await db.flush()


# ---------- SKUs ----------


async def list_all_skus(
    db: AsyncSession, *, product_id: str | None = None
) -> list[Sku]:
    stmt = select(Sku).options(selectinload(Sku.price_overrides))
    if product_id is not None:
        stmt = stmt.where(Sku.product_id == product_id)
    stmt = stmt.order_by(Sku.sort_order)
    return list((await db.execute(stmt)).scalars().all())


async def get_sku(db: AsyncSession, sku_id: str) -> Sku:
    stmt = (
        select(Sku).options(selectinload(Sku.price_overrides)).where(Sku.id == sku_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("sku not found")
    return row


async def create_sku(db: AsyncSession, body: SkuCreate) -> Sku:
    await get_product(db, body.product_id)
    row = Sku(
        id=new_id(),
        product_id=body.product_id,
        sku_code=body.sku_code,
        denomination=body.denomination,
        region=body.region,
        price_usd=body.price_usd,
        image_url=body.image_url,
        sort_order=body.sort_order,
        active=body.active,
        price_overrides=[
            SkuPrice(currency=o.currency, price=o.price) for o in body.price_overrides
        ],
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("sku_code already exists") from exc
    return row


async def update_sku(db: AsyncSession, sku_id: str, body: SkuUpdate) -> Sku:
    row = await get_sku(db, sku_id)
    for attr in (
        "sku_code",
        "denomination",
        "region",
        "price_usd",
        "image_url",
        "sort_order",
        "active",
    ):
        value = getattr(body, attr)
        if value is not None:
            setattr(row, attr, value)
    if body.price_overrides is not None:
        row.price_overrides = [
            SkuPrice(currency=o.currency, price=o.price) for o in body.price_overrides
        ]
    row.updated_at = now()
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("sku_code already exists") from exc
    return row


async def delete_sku(db: AsyncSession, sku_id: str) -> None:
    row = await get_sku(db, sku_id)
    await db.delete(row)
    await db.flush()


__all__ = [
    "create_brand",
    "create_category",
    "create_product",
    "create_sku",
    "delete_brand",
    "delete_category",
    "delete_product",
    "delete_sku",
    "get_brand",
    "get_category",
    "get_product",
    "get_sku",
    "list_all_brands",
    "list_all_categories",
    "list_all_products",
    "list_all_skus",
    "update_brand",
    "update_category",
    "update_product",
    "update_sku",
]
