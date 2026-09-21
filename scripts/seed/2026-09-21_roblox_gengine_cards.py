"""Roblox gift cards on G-Engine: a third source for five rungs we already sell.

Run inside the api container:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-09-21_roblox_gengine_cards.py

## What G-Engine has

Shop product **9, "Roblox Global"** (`GET /shop/denominations/9`, read live
2026-09-21) carries nine denominations. Mind the namespace: G-Engine's
*recharge* product 9 is Delta Force, and several `kind='game'` mappings point
at it. Shop and recharge ids are unrelated; `kind` is what tells them apart,
and a gift card is `kind='voucher'` — the same shape the Standoff 2 mappings
use (product 140, denominations 788-791).

    id   robux    price     stock
    36     100    4.6500        0
    37     200    4.7900        0
    38     400    6.2600        0
    39     800    9.4554        0
    727   2000   22.0932       10
    40    2200   25.4100        0
    41    2700   29.1000        0
    42    4500   49.8372        7
    199  10000   97.6242        0

Five overlap with our ladder and are mapped here. The other four (200, 400,
2200, 2700) are denominations we do not sell, and they are **deliberately not
created**: G-Engine's small rungs are priced nowhere near the other two
suppliers — 100 Robux at $4.65 against NOVA's $1.59 — so a 200 Robux SKU built
on $4.79 would undercut itself against two 100s. Creating them is a pricing
decision, not an import one.

## This changes no route and no cost

Every one of the five carries a `force_supplier` rule already (g2b for
800/2000/4500/10000, and 100 is NOVA-only), and a mapping is not a route. Nor
can it move the cost basis twice over: `cost_refresh.is_routed_supplier` lets
only the routed supplier write `Sku.cost_usdt`, and G-Engine is not in
`PRICE_COLLECTION_SUPPORTED_SUPPLIERS` at all, so its mappings are recorded
with "сбор цен не поддержан" and never quote a number.

Stock is the same story since the sweep became route-aware: a G-Engine
denomination sitting at 0 cannot hide a SKU that buys from G2B. That ordering
is not incidental — mapping a mostly-empty catalogue as a second source is
exactly what the route-aware read was written for.

## What the prices say, for whoever prices this later

Cheaper than the routed supplier on two rungs only: 2000 ($22.09 against G2B's
$22.95, ten in stock) and 10000 ($97.62 against $102.00, but zero in stock).
Dearer on 800 and 4500. 10000 Robux is currently out of stock at G2B **and**
G-Engine while NOVA holds twenty-nine — switching that one rung to NOVA is what
puts it back on the shelf.

Idempotent: mappings converge, nothing else is touched.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
PRODUCT_ID = "9"

#: ``(robux, denomination id)`` — only the rungs we actually sell.
LADDER: list[tuple[int, str]] = [
    (100, "36"),
    (800, "39"),
    (2000, "727"),
    (4500, "42"),
    (10000, "199"),
]


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        mapped = 0
        missing: list[str] = []
        for robux, denomination_id in LADDER:
            code = f"roblox-{robux}"
            sku_id = (
                await session.execute(select(Sku.id).where(Sku.sku_code == code))
            ).scalar_one_or_none()
            if sku_id is None:
                missing.append(code)
                continue
            await upsert_mapping(
                session,
                MappingUpsert(
                    sku_id=str(sku_id),
                    supplier_slug="gengine",
                    kind="voucher",
                    external_product_id=PRODUCT_ID,
                    external_variant_id=denomination_id,
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by=ADMIN_ID,
                ),
            )
            mapped += 1
        await session.commit()

    print(f"маппингов на gengine: {mapped}")
    if missing:
        print(f"ВНИМАНИЕ, не найдены SKU: {', '.join(missing)}")
    print("Маршруты и цены не тронуты: g-engine — третий источник, не поставщик по умолчанию.")


asyncio.run(main())
