"""Onboard Standoff 2 Gold gift codes from G-Engine's shop.

Run inside the api container (it needs the ``yupay`` package, the DB and
``GENGINE_API_KEY``):

    docker compose exec -T api python - < scripts/seed/2026-08-17_standoff2_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-17_standoff2_import.py

Then apply the SEO pack: ``scripts/seed/standoff2_seo.sql``.

**A promo code, not a top-up.** G-Engine sells Standoff 2 Gold as a voucher: we
hand over a code and the customer redeems it themselves, either in the official
web store or in-game via Inventory → Shop → Promocode. Nothing is credited to an
account by us, so the product asks for no game id — the code goes to the email
the order already carries, exactly like Discord and Roblox.

A top-up **by player id** is planned as a separate brand later. It is a different
purchase with different instructions, different fears and different search terms,
and `product_translations` has no `instructions` column — those live on the brand.
Folding both into one brand would mean one instruction block trying to describe
two incompatible flows. See the header of ``standoff2_seo.sql`` for how the two
keyword clusters are kept apart.

**Stock is real and small.** The four denominations held 15 / 5 / 5 / 5 units when
this was written, so it is read at import (which also proves the ids resolve) and
then kept fresh by the hourly sweep — ``integrations.stock_refresh`` reads
G-Engine stock per denomination via ``GET /shop/denominations/{product}``. The
count is never shown to customers; checkout refuses a SKU that has run dry and
the storefront greys it out.

Idempotent: brand and product are reused when present, existing ``sku_code``s are
skipped.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cat_schemas
from yupay.modules.catalog import admin_service as catalog
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment.suppliers.gengine_client import GEngineClient
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.integrations.stock_refresh import normalise_stock

CATEGORY_SLUG = "gift-cards"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

#: G-Engine shop product id, verified against GET /shop/products.
STANDOFF2_PRODUCT_ID = 140

BRAND_SLUG = "standoff-2"
PRODUCT_SLUG = "standoff-2-gold"

#: (sku_code, denomination id, label). Ids come from
#: GET /shop/denominations/140; prices and stock are read live, never baked in.
PACKS: list[tuple[str, int, str]] = [
    ("so2-gold-100", 788, "100 Gold"),
    ("so2-gold-500", 789, "500 Gold"),
    ("so2-gold-1000", 790, "1000 Gold"),
    ("so2-gold-3000", 791, "3000 Gold"),
]

BRAND_NAMES = {"ru": "Standoff 2", "en": "Standoff 2", "uz": "Standoff 2"}
PRODUCT_NAMES = {
    "ru": "Gold (промокод)",
    "en": "Gold (promo code)",
    "uz": "Gold (promokod)",
}


def _sell_price(cost: Decimal) -> Decimal:
    """cost × (1 + margin), rounded to cents the same way import_game does."""
    return (cost * (Decimal(1) + MARGIN_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _category_id(session: Any) -> str:
    row = (
        await session.execute(select(Category).where(Category.slug == CATEGORY_SLUG))
    ).scalar_one_or_none()
    if row is None:
        raise SystemExit(
            f"category {CATEGORY_SLUG} does not exist — run the gift cards import first"
        )
    return str(row.id)


async def _ensure_brand(session: Any, *, category_id: str) -> str:
    existing = (
        await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"brand {BRAND_SLUG}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_brand(
        session,
        cat_schemas.BrandCreate(
            slug=BRAND_SLUG,
            category_id=category_id,
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name)
                for loc, name in BRAND_NAMES.items()
            ],
        ),
    )
    print(f"brand {BRAND_SLUG}: created {row.id}")
    return str(row.id)


async def _ensure_product(session: Any, *, brand_id: str) -> str:
    existing = (
        await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"  product {PRODUCT_SLUG}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_product(
        session,
        cat_schemas.ProductCreate(
            slug=PRODUCT_SLUG,
            brand_id=brand_id,
            kind="voucher",
            supplier_hint="gengine",
            # No fields: the customer redeems the code themselves, so there is
            # no account for us to credit. The code goes to the order's email.
            required_fields=[],
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name)
                for loc, name in PRODUCT_NAMES.items()
            ],
        ),
    )
    print(f"  product {PRODUCT_SLUG}: created {row.id}")
    return str(row.id)


async def main() -> None:
    settings = get_settings()
    if not settings.gengine_api_key:
        raise SystemExit("GENGINE_API_KEY is not set — the import needs it to read live prices")
    client = GEngineClient(
        api_key=settings.gengine_api_key,
        base_url=settings.gengine_base_url,
        timeout_seconds=settings.gengine_request_timeout_seconds,
    )

    rows = await client.list_shop_denominations(STANDOFF2_PRODUCT_ID)
    remote = {int(r["id"]): r for r in rows if isinstance(r, dict) and r.get("id") is not None}
    if not remote:
        raise SystemExit(
            f"G-Engine product {STANDOFF2_PRODUCT_ID} lists no denominations — "
            "refusing to create mappings that cannot be fulfilled"
        )

    async with get_session_factory()() as session:
        category_id = await _category_id(session)
        brand_id = await _ensure_brand(session, category_id=category_id)
        product_id = await _ensure_product(session, brand_id=brand_id)

        present = set(
            (
                await session.execute(
                    select(Sku.sku_code).where(Sku.sku_code.in_([c for c, _, _ in PACKS]))
                )
            )
            .scalars()
            .all()
        )

        for position, (sku_code, denom_id, label) in enumerate(PACKS):
            if sku_code in present:
                print(f"    {sku_code}: exists — skipped")
                continue
            row = remote.get(denom_id)
            if row is None:
                raise SystemExit(
                    f"G-Engine denomination {denom_id} for {sku_code} is not listed — "
                    "refusing to create a mapping that cannot be fulfilled"
                )
            cost = Decimal(str(row.get("price") or 0))
            if cost <= 0:
                raise SystemExit(
                    f"G-Engine denomination {denom_id} is free or unpriced ({cost}) — "
                    "refusing to sell it at a guessed price"
                )
            stock = normalise_stock(row.get("stock"))

            sku = await catalog.create_sku(
                session,
                cat_schemas.SkuCreate(
                    product_id=product_id,
                    sku_code=sku_code,
                    denomination=label,
                    price_usd=_sell_price(cost),
                    cost_usdt=cost,
                    margin_percent=MARGIN_PERCENT,
                    sort_order=position,
                ),
            )
            # Seeded here rather than left to the first scheduler tick, so the
            # storefront is correct from the very first render.
            sku.supplier_stock = stock
            await upsert_mapping(
                session,
                MappingUpsert(
                    sku_id=sku.id,
                    supplier_slug="gengine",
                    kind="voucher",
                    external_product_id=str(STANDOFF2_PRODUCT_ID),
                    # The shop buys by denomination; the product id is what the
                    # stock sweep queries.
                    external_variant_id=str(denom_id),
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by=ADMIN_ID,
                ),
            )
            print(
                f"    {sku_code}: denom={denom_id} cost={cost} "
                f"price={_sell_price(cost)} stock={stock}"
            )

        await session.commit()
        print("committed")


asyncio.run(main())
