"""Seed the CS2 skins purchase line: brand, product, variable-amount SKU, waxpeer mapping.

Plan 3a Task 1 (docs/superpowers/plans/2026-09-28-cs2-skins-purchase-backend.md). Same shape
and rules as ``2026-09-03_steam_gifts.py`` — dry run by default, ``--apply`` commits, every
row looked up by its natural key and the managed fields re-synced on each run:

    docker compose exec -T api python - < scripts/seed/2026-09-29_cs2_skin_sku.py -- --apply

* Brand ``cs2-skins`` («Скины CS2»), in the ``steam`` brand's category. The storefronts route
  it to their own pages (web ``/skins``, mini app ``/cs2-market``) — plan 3b.
* Product ``cs2-skin``, ``kind="top_up"``, form ``slug`` / ``listing_id`` / ``tradelink`` — the
  keys ``skins/checkout.price_skin_line`` reads.
* SKU ``cs2-skin`` — variable amount; ``price_usd``/``rate_multiplier`` are unused placeholders
  (the line is priced from the live listing). ``visible_b2b`` stays false: resellers do not
  get skins until plan 4. A variable-amount SKU is never in the Merchant Center feed.
* ``sku_supplier_mapping (sku, 'waxpeer')`` at ``kind='skin'`` (legal since migration 0089),
  inserted directly — ``WaxpeerFulfiller`` branches on the kind alone.
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

BRAND_SLUG = "cs2-skins"
PRODUCT_SLUG = "cs2-skin"
SKU_CODE = "cs2-skin"
SUPPLIER_SLUG = "waxpeer"
MAPPING_KIND = "skin"
MAPPING_EXTERNAL_PRODUCT_ID = "cs2-listings"  # informational only
MAPPING_QUANTITY = 1

BRAND_NAME = {"ru": "Скины CS2", "en": "CS2 Skins", "uz": "CS2 skinlari"}
PRODUCT_NAME = {"ru": "Скин CS2", "en": "CS2 skin", "uz": "CS2 skini"}

REQUIRED_FIELDS: list[dict[str, Any]] = [
    {
        "key": "slug",
        "label": {"ru": "Скин", "en": "Skin", "uz": "Skin"},
        "type": "text",
        "required": True,
        "pattern": r"^[a-z0-9-]{1,200}$",
    },
    {
        "key": "listing_id",
        "label": {"ru": "Предложение", "en": "Offer", "uz": "Taklif"},
        "type": "number",
        "required": True,
    },
    {
        "key": "tradelink",
        "label": {"ru": "Трейд-ссылка", "en": "Trade link", "uz": "Treyd havola"},
        "type": "text",
        "required": True,
        "pattern": (
            r"^https://steamcommunity\.com/tradeoffer/new/\?partner=\d{1,12}&token=[\w-]{6,16}$"
        ),
    },
]

#: The pricing floor is $0.20 (``PricingRules.price_floor_usd``); $10 000 covers the dearest
#: knives and gloves on sale. The line is re-priced from the live listing regardless.
SKU_PRICE_USD_PLACEHOLDER = Decimal("1")
SKU_RATE_MULTIPLIER_PLACEHOLDER = Decimal("1")
SKU_MIN_AMOUNT_USD = Decimal("0.20")
SKU_MAX_AMOUNT_USD = Decimal("10000")

_SKU_MANAGED_FIELDS: dict[str, Decimal] = {
    "price_usd": SKU_PRICE_USD_PLACEHOLDER,
    "rate_multiplier": SKU_RATE_MULTIPLIER_PLACEHOLDER,
    "min_amount_usd": SKU_MIN_AMOUNT_USD,
    "max_amount_usd": SKU_MAX_AMOUNT_USD,
}


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
        raise SystemExit("no active category exists — cannot place the cs2-skins brand")
    return str(category.id)


async def _get_or_create_brand(session: AsyncSession) -> Brand:
    existing = (
        await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        by_locale = {t.locale: t for t in existing.translations}
        drifted = sorted(
            locale
            for locale, name in BRAND_NAME.items()
            if by_locale.get(locale) is None or by_locale[locale].name != name
        )
        if drifted:
            # Only ``name`` is managed here — every other translation field
            # (short_description/description/instructions/highlights) is
            # carried over from the stored row untouched, since
            # ``update_brand`` replaces the whole translations list.
            translations: list[cat_schemas.TranslationIn] = []
            for locale, name in BRAND_NAME.items():
                current = by_locale.get(locale)
                translations.append(
                    cat_schemas.TranslationIn(
                        locale=locale,  # type: ignore[arg-type]
                        name=name,
                        short_description=current.short_description if current else None,
                        description=current.description if current else None,
                        instructions=current.instructions if current else None,
                        highlights=(
                            list(current.highlights) if current and current.highlights else []
                        ),
                    )
                )
            existing = await catalog.update_brand(
                session, str(existing.id), cat_schemas.BrandUpdate(translations=translations)
            )
            print(
                f"brand {BRAND_SLUG}: translations updated {drifted} on existing row ({existing.id})"
            )
        else:
            print(f"brand {BRAND_SLUG}: already present, unchanged ({existing.id})")
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


def _required_fields_payload() -> list[dict[str, Any]]:
    """:data:`REQUIRED_FIELDS`, normalized through :class:`FormField` the
    same way a stored row is (``create_product``/``update_product`` both
    persist ``f.model_dump(mode="json")``) — so a diff against
    ``existing.required_fields`` compares like for like, not "no options
    key" against "options: null"."""
    return [FormField.model_validate(f).model_dump(mode="json") for f in REQUIRED_FIELDS]


async def _get_or_create_product(session: AsyncSession, *, brand: Brand) -> Product:
    existing = (
        await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        target = _required_fields_payload()
        if existing.required_fields != target:
            existing = await catalog.update_product(
                session,
                str(existing.id),
                cat_schemas.ProductUpdate(
                    required_fields=[FormField.model_validate(f) for f in REQUIRED_FIELDS]  # type: ignore[arg-type]
                ),
            )
            print(
                f"product {PRODUCT_SLUG}: required_fields updated on existing row ({existing.id})"
            )
        else:
            print(f"product {PRODUCT_SLUG}: already present, unchanged ({existing.id})")
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
        drifted = {
            field: value
            for field, value in _SKU_MANAGED_FIELDS.items()
            if getattr(existing, field) != value
        }
        if drifted:
            existing = await catalog.update_sku(
                session, str(existing.id), cat_schemas.SkuUpdate(**drifted)
            )
            print(f"sku {SKU_CODE}: updated {sorted(drifted)} on existing row ({existing.id})")
        else:
            print(f"sku {SKU_CODE}: already present, unchanged ({existing.id})")
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

    # Inserted directly — see the module docstring.
    mapping = SkuSupplierMapping(
        sku_id=sku.id,
        supplier_slug=SUPPLIER_SLUG,
        kind=MAPPING_KIND,
        external_product_id=MAPPING_EXTERNAL_PRODUCT_ID,
        external_variant_id=None,
        quantity=MAPPING_QUANTITY,
        extra={},
        is_active=True,
        updated_by=ADMIN_ID,
    )
    session.add(mapping)
    await session.flush()
    print(f"mapping {sku.id}/{SUPPLIER_SLUG}: created (kind={MAPPING_KIND})")
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
        prog="2026-09-29_cs2_skin_sku",
        description="Seed the cs2-skins brand, product, SKU and waxpeer skin mapping.",
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
