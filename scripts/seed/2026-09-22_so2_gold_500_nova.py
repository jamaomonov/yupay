"""Standoff 2 — 500 Gold gets a second source on NOVA.

Run inside the api container:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-09-22_so2_gold_500_nova.py

NOVA's gift-card catalogue (`/api/v2/giftcards`) only surfaced with the
2026-09-21 sync (ADR-0090); before that its whole catalogue read as
top-ups-only. Read live 2026-09-22, its `standoff_2_global` category carries
exactly **one** denomination:

    card_id     name       price_usd    stock
    500_gold    500 Gold   6.822168     121

That is the only one of our four Standoff 2 rungs NOVA sells at all — 100,
1000 and 3000 Gold have no NOVA equivalent, and all three currently sit at
`supplier_stock=0` on G-Engine (their only route) with nothing to fall back
to. This seed does not touch them.

so2-gold-500 keeps its existing `force_supplier: gengine` rule untouched.
This is a second mapping only, the same shape the five older Roblox rungs
got on NOVA — an operator's switch and a second line in
"Сравнить поставщиков по бренду", nothing more. NOVA is marginally cheaper
today ($6.822168 vs G-Engine's $6.9258, ~1.5%), not a reason to reroute by
itself.

Idempotent: converges the mapping, touches nothing else.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
SKU_CODE = "so2-gold-500"
CATEGORY = "standoff_2_global"
CARD_ID = "500_gold"


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        sku_id = (
            await session.execute(select(Sku.id).where(Sku.sku_code == SKU_CODE))
        ).scalar_one_or_none()
        if sku_id is None:
            raise SystemExit(f"sku {SKU_CODE} not found")

        await upsert_mapping(
            session,
            MappingUpsert(
                sku_id=str(sku_id),
                supplier_slug="nova",
                kind="voucher",
                external_product_id=CATEGORY,
                external_variant_id=CARD_ID,
                quantity=1,
                extra={},
                is_active=True,
                updated_by=ADMIN_ID,
            ),
        )
        await session.commit()

    print(f"замаппил {SKU_CODE} -> nova:{CATEGORY}:{CARD_ID}")
    print("маршрут не тронут: gengine остаётся force_supplier, nova — второй источник.")


asyncio.run(main())
