"""Standoff 2 Gold by player id, filled by hand.

Run inside the api container (it needs the ``yupay`` package, the DB and FX):

    docker compose exec -T api python - < scripts/seed/2026-10-27_standoff2_by_id_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-10-27_standoff2_by_id_import.py

Then apply the copy: ``scripts/seed/2026-10-27_standoff2_by_id_seo.sql``.

**Its own brand, ``standoff-2-id``** (``/store/standoff-2-id``). The first run
on 2026-10-27 put this product on ``standoff-2`` and switched the promo-code
product off; the same day ``2026-10-27_standoff2_split.sql`` gave it a brand of
its own and put promo codes back on ``standoff-2``. On a fresh database run that
SQL first — it creates the brand this script expects. The buyer types a player
id, the order lands in the manual queue, an operator credits the Gold in the
official store (store.standoff2.com) and closes the task.

**The cost is the store's rouble price** (owner, 2026-10-27), kept on each SKU's
``manual`` mapping (``extra.cost`` / ``extra.cost_currency``). The hourly price
refresh turns it into ``cost_usdt`` at the current USD→RUB rate
(``integrations/manual_cost.py``), and the price follows at a 9 % margin. This
script runs the same refresh once, so the shelf is right from the first render.

**Player id:** digits, four or more, no upper cap (owner, 2026-10-27). No live
check — there is no API to ask; the owner may hand one over later.

The brand sits in the top-ups category (Free Fire's) and out of the reseller
catalogue (``visible_b2b``): a hand-filled order is not what the API promises.

Idempotent: the product and SKUs are reused when present, mappings upserted.
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
PRODUCT_SLUG = "standoff-2-gold-id"
#: The top-ups category, found through a game that lives in it: its slug is
#: ``top-ups`` on prod and ``games`` in older dev databases.
SIBLING_BRAND_SLUG = "free-fire"
MARGIN_PERCENT = Decimal("9")

#: (sku_code, label, store price in RUB) — store.standoff2.com/ru-RU, 2026-10-27.
PACKS: list[tuple[str, str, str]] = [
    ("so2-id-100", "100 Gold", "119"),
    ("so2-id-500", "500 Gold", "499"),
    ("so2-id-1000", "1000 Gold", "899"),
    ("so2-id-3000", "3000 Gold", "1999"),
]

PRODUCT_NAMES = {"ru": "Gold по ID", "en": "Gold by ID", "uz": "Gold ID orqali"}

_PLAYER_ID_HELP = {
    "ru": "ID — число в профиле игрока. Откройте профиль в игре и скопируйте ID целиком.",
    "en": "The ID is the number in your player profile. Open the profile in the game and copy "
    "the whole ID.",
    "uz": "ID — oʻyinchi profilidagi raqam. Oʻyinda profilni oching va ID ni toʻliq nusxalang.",
}


def _required_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID"},
            "required": True,
            "pattern": "^[0-9]{4,}$",
            "placeholder": {"ru": "12345678", "en": "12345678", "uz": "12345678"},
            "help_text": _PLAYER_ID_HELP,
        }
    ]


async def _brand(session: Any) -> Brand:
    brand = (
        await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
    ).scalar_one_or_none()
    if brand is None:
        raise SystemExit(f"brand {BRAND_SLUG} does not exist")
    sibling = (
        await session.execute(select(Brand).where(Brand.slug == SIBLING_BRAND_SLUG))
    ).scalar_one()
    brand.category_id = sibling.category_id
    brand.visible_b2b = False
    return brand


async def _product(session: Any, *, brand_id: str) -> str:
    existing = (
        await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"product {PRODUCT_SLUG}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_product(
        session,
        cat_schemas.ProductCreate(
            slug=PRODUCT_SLUG,
            brand_id=brand_id,
            kind="top_up",
            supplier_hint="manual",
            required_fields=_required_fields(),  # type: ignore[arg-type]
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name)
                for loc, name in PRODUCT_NAMES.items()
            ],
        ),
    )
    print(f"product {PRODUCT_SLUG}: created {row.id}")
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
        brand = await _brand(session)
        product_id = await _product(session, brand_id=str(brand.id))
        for position, pack in enumerate(PACKS):
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
