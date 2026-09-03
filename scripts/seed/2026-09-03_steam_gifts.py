"""Seed the Steam Gifts catalog: brand, product, variable-amount SKU, mapping.

Run locally against the dev stack (``make dev`` up, Postgres published on
``127.0.0.1:5432``):

    cd apps/api && DATABASE_URL=postgresql+asyncpg://yupay_app:yupay_app@localhost:5432/yupay \\
        uv run python ../../scripts/seed/2026-09-03_steam_gifts.py
    cd apps/api && DATABASE_URL=postgresql+asyncpg://yupay_app:yupay_app@localhost:5432/yupay \\
        uv run python ../../scripts/seed/2026-09-03_steam_gifts.py --apply

or inside the api container, where ``DATABASE_URL`` is already set:

    docker compose exec -T api python - < scripts/seed/2026-09-03_steam_gifts.py -- --apply

Default is a **dry run**: everything below is built and flushed inside one
transaction so the printed summary reflects exactly what would land, then the
transaction is rolled back. Pass ``--apply`` to commit.

What it creates, all gated behind ``STEAM_GIFTS_ENABLED`` (Task 4's checkout
hook, Task 5's fulfiller) — this script only lays the catalog rows down; the
flag stays whatever the environment has it as:

* Brand ``steam-gifts`` (RU "Steam Гифты" / EN "Steam Gifts" / UZ "Steam
  sovg'alari"), in the same category as the existing ``steam`` brand.
* Product ``steam-gift``, ``kind="top_up"``, with the four-field form schema
  ``gifts/checkout.py`` expects verbatim: ``app_id``, ``package_id``,
  ``region``, ``invite_url``. The schema is round-tripped through
  :class:`yupay.modules.catalog.schemas.FormField` before anything is written
  — a typo'd key or an unsafe regex fails here, not as a 422 on the first
  real checkout.
* SKU ``steam-gift`` — variable-amount, mirroring the sibling
  ``steam-wallet-usd`` line: the customer's dollar amount is billed directly,
  no ``amount_unit`` conversion. ``price_usd`` and ``rate_multiplier`` are
  unused placeholders (``price_gift_line`` re-derives the real price from the
  live G-Engine catalog and the admin margin, never from this row); both
  columns are just NOT NULL and CHECK-bound so they need *a* value.
* The ``sku_supplier_mapping`` row ``(sku_id, 'gengine')`` at ``kind='gift'``
  — legal since migration 0064. Inserted directly with SQLAlchemy, **not**
  via ``integrations.service.upsert_mapping``: that helper's cost-refresh
  path prices packaged denominations, which a gift line has none of.
  ``external_product_id`` is informational only — ``fulfillment/suppliers/
  gengine.py`` routes to :func:`gengine_gifts.fulfill_gift` on
  ``mapping.kind == "gift"`` alone, never on this column.

No sourcing rule is created: ``sourcing._resolve_auto`` already sends a
``top_up`` product with one active mapping to ``supplier:gengine``.

Idempotent: each row is looked up by its natural key (slug / sku_code /
``(sku_id, supplier_slug)``) before anything is built; an existing row is
left untouched and reported as "already present". A second ``--apply`` run
changes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cat_schemas
from yupay.modules.catalog import admin_service as catalog
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.catalog.schemas import FormField
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import get_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"

BRAND_SLUG = "steam-gifts"
PRODUCT_SLUG = "steam-gift"
SKU_CODE = "steam-gift"
SUPPLIER_SLUG = "gengine"
# Informational only — see the module docstring. Not consumed by the fulfiller.
MAPPING_EXTERNAL_PRODUCT_ID = "gifts-apps"
MAPPING_QUANTITY = 1

BRAND_NAME = {"ru": "Steam Гифты", "en": "Steam Gifts", "uz": "Steam sovg'alari"}
PRODUCT_NAME = {"ru": "Подарок Steam", "en": "Steam Gift", "uz": "Steam sovg'asi"}

# ``gifts/checkout.py::price_gift_line`` reads exactly these four keys off
# ``fulfillment_data`` — ``app_id``, ``package_id``, ``region``,
# ``invite_url`` — and ``ProductCreate.required_fields`` (extra="forbid" on
# ``FormField``) is the 422 layer in front of it. Keep this block byte-for-
# byte what the task brief specifies.
REQUIRED_FIELDS: list[dict[str, Any]] = [
    {
        "key": "app_id",
        "label": {"ru": "ID игры", "en": "App ID", "uz": "O'yin ID"},
        "type": "number",
        "required": True,
    },
    {
        "key": "package_id",
        "label": {"ru": "Издание", "en": "Edition", "uz": "Nashr"},
        "type": "number",
        "required": True,
    },
    {
        "key": "region",
        "label": {"ru": "Регион", "en": "Region", "uz": "Mintaqa"},
        "type": "select",
        "required": True,
        "options": [
            {
                "value": "CIS",
                "label": {"ru": "СНГ (без России)", "en": "CIS (no Russia)", "uz": "MDH (Rossiyasiz)"},
            },
            {"value": "RU", "label": {"ru": "Россия", "en": "Russia", "uz": "Rossiya"}},
            {"value": "KZ", "label": {"ru": "Казахстан", "en": "Kazakhstan", "uz": "Qozog'iston"}},
            {"value": "UA", "label": {"ru": "Украина", "en": "Ukraine", "uz": "Ukraina"}},
        ],
    },
    {
        "key": "invite_url",
        "label": {
            "ru": "Ссылка на профиль Steam",
            "en": "Steam profile link",
            "uz": "Steam profil havolasi",
        },
        "type": "text",
        "required": True,
        "pattern": (
            r"^(https?://)?(steamcommunity\.com/(profiles/\d{17}|id/[A-Za-z0-9_-]{2,32})"
            r"|s\.team/p/[A-Za-z0-9/_-]+)/?$"
        ),
    },
]

# ``price_usd``/``rate_multiplier`` — unused placeholders, both NOT NULL /
# CHECK-bound columns; ``price_gift_line`` never reads either. Bounds mirror
# ``steam-wallet-usd``'s ``max_amount_usd`` (300); the floor is a business
# minimum (a $0.50 gift is more likely a fat-fingered amount than a sale).
SKU_PRICE_USD_PLACEHOLDER = Decimal("1")
SKU_RATE_MULTIPLIER_PLACEHOLDER = Decimal("1")
SKU_MIN_AMOUNT_USD = Decimal("0.50")
SKU_MAX_AMOUNT_USD = Decimal("300")


def _validate_required_fields() -> None:
    """Round-trip :data:`REQUIRED_FIELDS` through :class:`FormField`.

    Fails fast, before any DB work: an unknown key, an unsafe regex, or a
    malformed option would otherwise only surface as a 422 the first time a
    customer opens checkout.
    """
    for field in REQUIRED_FIELDS:
        FormField.model_validate(field)


async def _resolve_category_id(session: AsyncSession) -> str:
    """The ``steam`` brand's category, or the first active category as a fallback."""
    steam_brand = (
        await session.execute(select(Brand).where(Brand.slug == "steam"))
    ).scalar_one_or_none()
    if steam_brand is not None:
        return str(steam_brand.category_id)
    print("  warning: brand 'steam' not found — falling back to the first active category")
    category = (
        (
            await session.execute(
                select(Category)
                .where(Category.active.is_(True))
                .order_by(Category.sort_order, Category.slug)
            )
        )
        .scalars()
        .first()
    )
    if category is None:
        raise SystemExit("no active category exists — cannot place the steam-gifts brand")
    return str(category.id)


async def _get_or_create_brand(session: AsyncSession) -> Brand:
    existing = (
        await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"brand {BRAND_SLUG}: already present ({existing.id})")
        return existing

    category_id = await _resolve_category_id(session)
    brand = await catalog.create_brand(
        session,
        cat_schemas.BrandCreate(
            slug=BRAND_SLUG,
            category_id=category_id,
            translations=[
                cat_schemas.TranslationIn(locale=locale, name=name)  # type: ignore[arg-type]
                for locale, name in BRAND_NAME.items()
            ],
        ),
    )
    print(f"brand {BRAND_SLUG}: created ({brand.id}) in category {category_id}")
    return brand


async def _get_or_create_product(session: AsyncSession, *, brand: Brand) -> Product:
    existing = (
        await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"product {PRODUCT_SLUG}: already present ({existing.id})")
        return existing

    product = await catalog.create_product(
        session,
        cat_schemas.ProductCreate(
            slug=PRODUCT_SLUG,
            brand_id=str(brand.id),
            kind="top_up",
            required_fields=[FormField.model_validate(f) for f in REQUIRED_FIELDS],  # type: ignore[arg-type]
            translations=[
                cat_schemas.TranslationIn(locale=locale, name=name)  # type: ignore[arg-type]
                for locale, name in PRODUCT_NAME.items()
            ],
        ),
    )
    print(f"product {PRODUCT_SLUG}: created ({product.id}) under brand {brand.id}")
    return product


async def _get_or_create_sku(session: AsyncSession, *, product: Product) -> Sku:
    existing = (
        await session.execute(select(Sku).where(Sku.sku_code == SKU_CODE))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"sku {SKU_CODE}: already present ({existing.id})")
        return existing

    sku = await catalog.create_sku(
        session,
        cat_schemas.SkuCreate(
            product_id=str(product.id),
            sku_code=SKU_CODE,
            denomination="Любая сумма",
            price_usd=SKU_PRICE_USD_PLACEHOLDER,
            variable_amount=True,
            min_amount_usd=SKU_MIN_AMOUNT_USD,
            max_amount_usd=SKU_MAX_AMOUNT_USD,
            rate_multiplier=SKU_RATE_MULTIPLIER_PLACEHOLDER,
        ),
    )
    print(f"sku {SKU_CODE}: created ({sku.id}) under product {product.id}")
    return sku


async def _get_or_create_mapping(session: AsyncSession, *, sku: Sku) -> SkuSupplierMapping:
    existing = await get_mapping(session, sku_id=sku.id, supplier_slug=SUPPLIER_SLUG)
    if existing is not None:
        print(f"mapping {sku.id}/{SUPPLIER_SLUG}: already present (kind={existing.kind})")
        return existing

    # Inserted directly, not via integrations.service.upsert_mapping — see
    # the module docstring: that helper's cost-refresh path knows nothing
    # about gift lines.
    mapping = SkuSupplierMapping(
        sku_id=sku.id,
        supplier_slug=SUPPLIER_SLUG,
        kind="gift",
        external_product_id=MAPPING_EXTERNAL_PRODUCT_ID,
        external_variant_id=None,
        quantity=MAPPING_QUANTITY,
        extra={},
        is_active=True,
        updated_by=ADMIN_ID,
    )
    session.add(mapping)
    await session.flush()
    print(f"mapping {sku.id}/{SUPPLIER_SLUG}: created (kind=gift)")
    return mapping


async def _print_summary(
    *, brand: Brand, product: Product, sku: Sku, mapping: SkuSupplierMapping
) -> None:
    print("\nsummary:")
    print(f"  brand.id   = {brand.id}")
    print(f"  product.id = {product.id}")
    print(f"  sku.id     = {sku.id}")
    print(f"  mapping    = ({mapping.sku_id}, {mapping.supplier_slug}) kind={mapping.kind}")


async def run(*, apply: bool) -> None:
    _validate_required_fields()
    async with get_session_factory()() as session:
        brand = await _get_or_create_brand(session)
        product = await _get_or_create_product(session, brand=brand)
        sku = await _get_or_create_sku(session, product=product)
        mapping = await _get_or_create_mapping(session, sku=sku)
        await _print_summary(brand=brand, product=product, sku=sku, mapping=mapping)

        if apply:
            await session.commit()
            print("\ncommitted")
        else:
            await session.rollback()
            print("\ndry run — rolled back, nothing was written (pass --apply to commit)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="2026-09-03_steam_gifts",
        description="Seed the steam-gifts brand, product, SKU and gengine gift mapping.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the writes (default: dry run — build everything, then roll back)",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    await run(apply=args.apply)


if __name__ == "__main__":
    asyncio.run(main())
