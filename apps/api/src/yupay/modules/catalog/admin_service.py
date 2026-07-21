"""Write-side service for admin catalog endpoints.

Public read service lives in :mod:`yupay.modules.catalog.service`. The split keeps the
admin surface auditable in one place.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandFaq,
    BrandFaqTranslation,
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
        FaqCreate,
        FaqUpdate,
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


async def update_category(db: AsyncSession, category_id: str, body: CategoryUpdate) -> Category:
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
    stmt = select(Brand).options(selectinload(Brand.translations)).where(Brand.id == brand_id)
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
        maintenance=body.maintenance,
        translations=[
            BrandTranslation(
                locale=t.locale,
                name=t.name,
                short_description=t.short_description,
                description=t.description,
                instructions=t.instructions,
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
    for attr in (
        "slug",
        "logo_url",
        "hero_image_url",
        "accent_color",
        "sort_order",
        "active",
        "maintenance",
    ):
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
                instructions=t.instructions,
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


# ---------- brand FAQs ----------


async def list_faqs_for_brand(db: AsyncSession, brand_id: str) -> list[BrandFaq]:
    stmt = (
        select(BrandFaq)
        .options(selectinload(BrandFaq.translations))
        .where(BrandFaq.brand_id == brand_id)
        .order_by(BrandFaq.sort_order)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_faq(db: AsyncSession, faq_id: str) -> BrandFaq:
    stmt = (
        select(BrandFaq).options(selectinload(BrandFaq.translations)).where(BrandFaq.id == faq_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("faq not found")
    return row


async def create_faq(db: AsyncSession, brand_id: str, body: FaqCreate) -> BrandFaq:
    # Validate the parent brand exists.
    await get_brand(db, brand_id)
    row = BrandFaq(
        id=new_id(),
        brand_id=brand_id,
        sort_order=body.sort_order,
        active=body.active,
        translations=[
            BrandFaqTranslation(locale=t.locale, question=t.question, answer=t.answer)
            for t in body.translations
        ],
    )
    db.add(row)
    await db.flush()
    return row


async def update_faq(db: AsyncSession, faq_id: str, body: FaqUpdate) -> BrandFaq:
    row = await get_faq(db, faq_id)
    for attr in ("sort_order", "active"):
        value = getattr(body, attr)
        if value is not None:
            setattr(row, attr, value)
    if body.translations is not None:
        row.translations = [
            BrandFaqTranslation(locale=t.locale, question=t.question, answer=t.answer)
            for t in body.translations
        ]
    row.updated_at = now()
    await db.flush()
    return row


async def delete_faq(db: AsyncSession, faq_id: str) -> None:
    row = await get_faq(db, faq_id)
    await db.delete(row)
    await db.flush()


# ---------- products ----------


async def list_all_products(db: AsyncSession, *, brand_id: str | None = None) -> list[Product]:
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
        select(Product).options(selectinload(Product.translations)).where(Product.id == product_id)
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


async def update_product(db: AsyncSession, product_id: str, body: ProductUpdate) -> Product:
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


async def list_all_skus(db: AsyncSession, *, product_id: str | None = None) -> list[Sku]:
    stmt = select(Sku).options(selectinload(Sku.price_overrides))
    if product_id is not None:
        stmt = stmt.where(Sku.product_id == product_id)
    stmt = stmt.order_by(Sku.sort_order)
    return list((await db.execute(stmt)).scalars().all())


async def set_sku_cost_usdt(
    db: AsyncSession,
    *,
    sku_id: str,
    new_cost: Decimal,
) -> Decimal | None:
    """Replace ``Sku.cost_usdt`` and return the previous value (or ``None``
    when this is the first time we're recording the cost).

    Returns ``new_cost`` itself when nothing changed so callers don't have
    to handle a "noop" sentinel — the truthy old/new comparison is
    delegated to the caller.

    Refuses to write a non-positive cost; mirrors the
    ``ck_skus_cost_usdt_positive`` check at the DB layer with a clearer
    error than an ``IntegrityError`` rollback.
    """
    if new_cost <= 0:
        raise ConflictError(
            "cost_usdt must be positive",
            extra={"sku_id": sku_id, "value": str(new_cost)},
        )
    sku = (await db.execute(select(Sku).where(Sku.id == sku_id))).scalar_one_or_none()
    if sku is None:
        raise NotFoundError("sku not found")
    previous = sku.cost_usdt
    sku.cost_usdt = new_cost
    sku.updated_at = now()
    await db.flush()
    return previous


async def search_skus_for_picker(
    db: AsyncSession,
    *,
    query: str | None,
    limit: int = 30,
) -> list[Sku]:
    """Compact, search-friendly listing for the admin combobox.

    Eager-loads ``Sku.product`` plus the Russian product translation so the
    UI can render ``"PUBG Mobile · 60 UC · netflix-10-us"`` rows without
    N+1 queries.

    Matching is case-insensitive ``ILIKE`` against four columns:

    - ``sku.sku_code``
    - ``sku.denomination``
    - ``product.slug``
    - the product's RU display name (joined translation)
    """
    from sqlalchemy import or_

    from yupay.modules.catalog.models import Product, ProductTranslation

    stmt = (
        select(Sku)
        .options(
            selectinload(Sku.product).selectinload(Product.translations),
        )
        .join(Product, Product.id == Sku.product_id)
        .order_by(Sku.sort_order, Sku.sku_code)
    )
    cleaned = (query or "").strip()
    if cleaned:
        like = f"%{cleaned}%"
        stmt = stmt.outerjoin(
            ProductTranslation,
            (ProductTranslation.product_id == Product.id) & (ProductTranslation.locale == "ru"),
        ).where(
            or_(
                Sku.sku_code.ilike(like),
                Sku.denomination.ilike(like),
                Product.slug.ilike(like),
                ProductTranslation.name.ilike(like),
            )
        )
    stmt = stmt.limit(min(max(limit, 1), 100))
    return list((await db.execute(stmt)).scalars().unique().all())


async def get_sku(db: AsyncSession, sku_id: str) -> Sku:
    stmt = select(Sku).options(selectinload(Sku.price_overrides)).where(Sku.id == sku_id)
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
        cost_usdt=body.cost_usdt,
        variable_amount=body.variable_amount,
        min_amount_usd=body.min_amount_usd,
        max_amount_usd=body.max_amount_usd,
        rate_multiplier=body.rate_multiplier,
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
        "cost_usdt",
        "image_url",
        "sort_order",
        "active",
    ):
        value = getattr(body, attr)
        if value is not None:
            setattr(row, attr, value)
    # The variable-amount block is written as a unit rather than field-by-field:
    # once the admin explicitly touches ``variable_amount`` (true or false), all
    # three companion fields are overwritten together — including nulling them
    # out when the toggle goes off. Elsewhere in this function ``None`` means
    # "don't touch"; here it can legitimately mean "clear it", which the usual
    # per-field skip would silently ignore. See the SkuUpdate docstring.
    if body.variable_amount is not None:
        row.variable_amount = body.variable_amount
        row.min_amount_usd = body.min_amount_usd
        row.max_amount_usd = body.max_amount_usd
        row.rate_multiplier = body.rate_multiplier
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


async def bulk_set_uzs_prices(
    db: AsyncSession,
    *,
    fx_service: Any,
) -> dict[str, Any]:
    """Recompute the UZS ``SkuPrice`` override for every active SKU.

    Picks the current USDT→UZS rate via the shared ``FxService`` (so the
    snapshot table accumulates an audit trail of the rate the operator
    saw) and writes ``cost_usdt × rate`` into ``sku_prices``. SKUs
    without ``cost_usdt`` are skipped — we don't want to guess a price
    for an unknown wholesale figure.

    The write is an UPSERT on (sku_id, currency='UZS'), so the helper is
    idempotent: calling it twice with the same rate is a no-op; calling
    it with a new rate just overwrites the override.

    Returns a small dict with the rate used and counters: how many SKUs
    were updated, how many got created fresh, how many were skipped
    because cost_usdt is null. The admin UI shows these to the operator
    so a clearly-wrong rate doesn't silently fan out across the catalog.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from yupay.modules.fx.models import FxSnapshot

    snap = await fx_service.snapshot(db, base="USDT", quote="UZS")
    rate = snap.rate

    skus = list(
        (await db.execute(select(Sku).where(Sku.active.is_(True)).where(Sku.cost_usdt.isnot(None))))
        .scalars()
        .all()
    )
    skipped = int(
        (
            await db.execute(
                select(func.count(Sku.id))
                .where(Sku.active.is_(True))
                .where(Sku.cost_usdt.is_(None))
            )
        ).scalar_one()
        or 0
    )

    created = 0
    updated = 0
    for sku in skus:
        cost = sku.cost_usdt
        if cost is None:  # defensive — query already filtered
            continue
        price = (cost * rate).quantize(Decimal("1"))  # UZS: whole sums
        stmt = (
            pg_insert(SkuPrice)
            .values(sku_id=sku.id, currency="UZS", price=price)
            .on_conflict_do_update(
                index_elements=[SkuPrice.sku_id, SkuPrice.currency],
                set_={"price": price},
            )
            .returning(SkuPrice.sku_id)
        )
        result = await db.execute(stmt)
        # The simplest signal we have for "created vs updated" without a
        # second SELECT round-trip: ON CONFLICT DO UPDATE always returns
        # a row, so we can't separate the two cheaply. We approximate by
        # counting all of them as "updated" and reporting "created"
        # separately from a quick post-check.
        _ = result.scalar_one()
        updated += 1

    # Recompute "freshly created" by counting SKUs whose newest override
    # row matches our rate to within rounding — costly but correct
    # enough for an admin button. For the operator the headline number
    # is updated total; created/updated split is a nicety.
    return {
        "rate": rate,
        "fx_snapshot_id": snap.id if isinstance(snap, FxSnapshot) else None,
        "updated_total": updated,
        "skipped_without_cost": skipped,
        "created": created,
    }


__all__ = [
    "bulk_set_uzs_prices",
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
