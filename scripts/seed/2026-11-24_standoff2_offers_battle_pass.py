"""Standoff 2 by ID: «Акции» and «Battle Pass», filled by hand like the Gold.

Run inside the api container after ``2026-10-27_standoff2_by_id_import.py``:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-11-24_standoff2_offers_battle_pass.py

Two more products on ``standoff-2-id`` (owner, 2026-11-24), each its own
section on the brand page under the Gold: the store's limited offer (Contender
skins) and the season's Gold Pass with level packs. Same mechanics as the Gold:
the buyer types a player id, the order lands in the manual queue, an operator
buys it in store.standoff2.com. The cost is the store's rouble price on the
``manual`` mapping, converted hourly (``integrations/manual_cost.py``), 9 %
margin.

Both are seasonal: when the offer or the season ends, switch the SKUs off in
the admin (or replace them with the next season's).

Idempotent: products and SKUs are reused when present, mappings upserted.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cat_schemas
from yupay.modules.catalog import admin_service as catalog
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fx.factory import build_default_service
from yupay.modules.integrations.cost_refresh import refresh_sku_cost_for_mapping
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
BRAND_SLUG = "standoff-2-id"
#: The Gold product: its player-id field is copied so all three ask the same.
GOLD_SLUG = "standoff-2-gold-id"
MARGIN_PERCENT = Decimal("9")

#: (product slug, sort, names, [(sku_code, label, store price in RUB)]) —
#: store.standoff2.com/ru-RU, 2026-11-24.
PRODUCTS: list[tuple[str, int, dict[str, str], list[tuple[str, str, str]]]] = [
    (
        "standoff-2-offers-id",
        1,
        {"ru": "Акции", "en": "Offers", "uz": "Aksiyalar"},
        [
            ("so2-id-m16-contender", "M16 «Contender» ST", "1199"),
            ("so2-id-akr12-contender", "AKR12 «Contender» ST", "1199"),
        ],
    ),
    (
        "standoff-2-battle-pass-id",
        2,
        {"ru": "Battle Pass", "en": "Battle Pass", "uz": "Battle Pass"},
        [
            ("so2-id-gold-pass", "Gold Pass", "599"),
            ("so2-id-gold-pass-10", "Gold Pass + 10 Levels", "1099"),
            ("so2-id-level-1", "+1 Level", "89"),
            ("so2-id-level-10", "+10 Levels", "699"),
            ("so2-id-level-20", "+20 Levels", "1349"),
            ("so2-id-level-45", "+45 Levels", "2399"),
        ],
    ),
]


async def _product(
    session: Any, *, brand_id: str, slug: str, sort: int, names: dict[str, str], fields: Any
) -> str:
    existing = (
        await session.execute(select(Product).where(Product.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"product {slug}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_product(
        session,
        cat_schemas.ProductCreate(
            slug=slug,
            brand_id=brand_id,
            kind="top_up",
            supplier_hint="manual",
            sort_order=sort,
            required_fields=fields,
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name) for loc, name in names.items()
            ],
        ),
    )
    print(f"product {slug}: created {row.id}")
    return str(row.id)


async def _sku(
    session: Any, *, product_id: str, position: int, pack: tuple[str, str, str], rate: Decimal
) -> str:
    sku_code, label, rub = pack
    existing = (
        await session.execute(select(Sku).where(Sku.sku_code == sku_code))
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing.id)
    cost = (Decimal(rub) / rate).quantize(Decimal("0.000001"))
    price = (cost * (1 + MARGIN_PERCENT / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sku = await catalog.create_sku(
        session,
        cat_schemas.SkuCreate(
            product_id=product_id,
            sku_code=sku_code,
            denomination=label,
            price_usd=price,
            cost_usdt=cost,
            margin_percent=MARGIN_PERCENT,
            sort_order=position,
        ),
    )
    return str(sku.id)


async def main() -> None:
    rate = (await build_default_service().get_rate("USD", "RUB")).rate
    print(f"USD→RUB {rate}")
    async with get_session_factory()() as session:
        brand = (await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))).scalar_one()
        gold = (
            await session.execute(select(Product).where(Product.slug == GOLD_SLUG))
        ).scalar_one()
        for slug, sort, names, packs in PRODUCTS:
            product_id = await _product(
                session,
                brand_id=str(brand.id),
                slug=slug,
                sort=sort,
                names=names,
                fields=gold.required_fields,
            )
            for position, pack in enumerate(packs):
                sku_id = await _sku(
                    session, product_id=product_id, position=position, pack=pack, rate=rate
                )
                await upsert_mapping(
                    session,
                    MappingUpsert(
                        sku_id=sku_id,
                        supplier_slug="manual",
                        kind="game",
                        external_product_id="store.standoff2.com",
                        external_variant_id=pack[1],
                        quantity=1,
                        extra={"cost": pack[2], "cost_currency": "RUB"},
                        is_active=True,
                        updated_by=ADMIN_ID,
                    ),
                )
                mapping = await session.get(SkuSupplierMapping, (sku_id, "manual"))
                outcome = await refresh_sku_cost_for_mapping(session, mapping=mapping)
                sku = await session.get(Sku, sku_id)
                print(
                    f"  {pack[0]}: {pack[2]} RUB → cost {sku.cost_usdt} price {sku.price_usd} "
                    f"({outcome.reason or outcome.source})"
                )
        await session.commit()
        print("committed")


asyncio.run(main())
