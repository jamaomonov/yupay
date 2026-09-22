"""Roblox on G2B: the whole ladder, not the third of it we had.

Run inside the api container. Preview first, then apply:

    docker exec -i -e APPLY=0 yupay-prod-api-1 python - < scripts/seed/2026-09-22_roblox_g2b_full_ladder.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-09-22_roblox_g2b_full_ladder.py

## What G2B has that we did not

Their `Roblox Global` category (`GET /products`, category_id 20, read live
2026-09-22) carries **fifteen** denominations. We sold nine and had a G2B
mapping on five of them. Cost and stock as read that day:

        robux   g2b id   cost $    stock   we had it?
           50     1201     0.98      113   yes, NOVA only
          100     1170     1.60      993   yes, NOVA + G-Engine
          200     1171     2.85     1138   NO
          800      107     9.06      237   yes, mapped
         1000     1154    11.40       72   yes, mapped
         1500     1194    17.00       11   NO
         2000      108    22.95       97   yes, mapped
         2500     1195    27.47        6   yes, NOVA only
         3000     1196    33.40        0   yes, NOVA only
         4000     1197    43.90        3   NO
         4500      109    48.50       24   yes, mapped
         5250     1198    54.60        6   NO
        10000      110   102.00        0   yes, mapped
        11000     1199   109.40        5   NO
        24000     1200   218.45        5   NO

So this seed does two separate things:

- **Maps** the four rungs we sell but never mapped to G2B — 50, 100, 2500 and
  3000 — as a second source. Nothing is re-priced and nothing is rerouted.
- **Creates** the six we did not sell at all — 200, 1500, 4000, 5250, 11000
  and 24000 — priced off G2B's cost.

## Two rungs where G2B undercuts the supplier we route to

`roblox-2500` and `roblox-3000` are both pinned to NOVA, and G2B is cheaper:
2500 is $27.47 against NOVA's $28.412916 (−3.3%), 3000 is $33.40 against
$35.155524 (−5.0%). This seed **does not act on that** — rerouting moves real
orders and is an operator's decision, not a seed's, and G2B's 3000 is at zero
stock as of the read anyway. The mapping is what puts both numbers side by
side on the sourcing screen so the decision can be made there.

## Why the six new ones need no sourcing rule

`sourcing._pick_auto_mapping_slug` picks the oldest active mapping that is not
a `RESERVE_SUPPLIERS` member. G2B is not one, and it is their only mapping, so
auto resolves to G2B. That is deliberately better than pinning: if NOVA or
G-Engine ever gets mapped onto one of these, auto keeps the incumbent instead
of silently handing somebody's order to a supplier nobody chose. Contrast the
NOVA-only rungs from 2026-09-21, which *had* to be pinned because auto refuses
to pick a reserve supplier and they would otherwise have routed nowhere.

## Stock is written once, then handed over

A new SKU with `supplier_stock` NULL reads as **in stock** (`Sku.in_stock`
treats NULL as untracked). Four of the six new rungs are thin — 4000 has three
codes, 11000 and 24000 five apiece — and one existing rung's G2B counter is at
zero, so leaving them NULL would put lines on the shelf we might not be able to
deliver for up to an hour. Each new SKU is therefore created with the count
read above; the hourly sweep owns it from the next pass on.

Margin 14%, rounded to the cent half-up — the same as rungs 50 through 4500.
(10000 sits at 13%; it already exists and is not touched.) `b2b_markup_pct` 6
and `visible_b2b` are copied from the existing rungs rather than defaulted,
which is 6% and visible against a catalogue default of 7%.

Idempotent: an existing `sku_code` is never re-priced, mappings converge,
`sort_order` is rewritten on every row so the ladder stays in amount order
after six insertions.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
PRODUCT_SLUG = "roblox-robux-global"
SUPPLIER = "g2b"
MARGIN = Decimal("14")
B2B_MARKUP = Decimal("6")
APPLY = os.environ.get("APPLY") == "1"

#: ``(robux, g2b product id, cost, stock)`` — G2B's whole Roblox Global
#: ladder, cheapest first, as read 2026-09-22. The rungs we already sell are
#: here too: the mapping loop needs their product ids, and a partial list
#: would be a second place to keep them in step.
LADDER: list[tuple[int, str, str, int]] = [
    (50, "1201", "0.98", 113),
    (100, "1170", "1.60", 993),
    (200, "1171", "2.85", 1138),
    (800, "107", "9.06", 237),
    (1000, "1154", "11.40", 72),
    (1500, "1194", "17.00", 11),
    (2000, "108", "22.95", 97),
    (2500, "1195", "27.47", 6),
    (3000, "1196", "33.40", 0),
    (4000, "1197", "43.90", 3),
    (4500, "109", "48.50", 24),
    (5250, "1198", "54.60", 6),
    (10000, "110", "102.00", 0),
    (11000, "1199", "109.40", 5),
    (24000, "1200", "218.45", 5),
]

#: The rungs we did not sell at all. Everything else already exists and is
#: only mapped here, never re-priced — its cost belongs to whichever supplier
#: it routes to, and the hourly refresh owns that.
NEW = {200, 1500, 4000, 5250, 11000, 24000}


def _price(cost: Decimal) -> Decimal:
    """Cost plus margin, to the cent, half-up — how the existing rungs round."""
    return (cost * (Decimal("1") + MARGIN / Decimal("100"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _create_sku(
    session: Any, *, product_id: str, robux: int, cost: Decimal, stock: int, position: int
) -> str:
    """Create one new rung and return its id.

    Split out of :func:`main` only to keep that loop under ruff's branch
    ceiling; nothing here is reusable elsewhere.
    """
    from yupay.modules.catalog import admin_schemas as cs
    from yupay.modules.catalog import admin_service as catalog

    sku = await catalog.create_sku(
        session,
        cs.SkuCreate(
            product_id=product_id,
            sku_code=f"roblox-{robux}",
            denomination=f"{robux} Robux",
            region="GLOBAL",
            price_usd=_price(cost),
            cost_usdt=cost,
            margin_percent=MARGIN,
            sort_order=position,
        ),
    )
    fresh = (await session.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    # Copied from the existing rungs, not defaulted: this brand sells to
    # resellers at 6%, the catalogue default is 7%.
    fresh.b2b_markup_pct = B2B_MARKUP
    fresh.visible_b2b = True
    # A NULL here reads as "in stock" — see the module docstring.
    fresh.supplier_stock = stock
    fresh.supplier_stock_at = datetime.now(UTC)
    sku_id: str = sku.id
    return sku_id


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        product_id = (
            await session.execute(select(Product.id).where(Product.slug == PRODUCT_SLUG))
        ).scalar_one_or_none()
        if product_id is None:
            raise SystemExit(f"product {PRODUCT_SLUG} not found")

        created: list[str] = []
        mapped: list[str] = []

        for position, (robux, g2b_id, cost_text, stock) in enumerate(LADDER):
            code = f"roblox-{robux}"
            cost = Decimal(cost_text)
            row = (
                await session.execute(select(Sku).where(Sku.sku_code == code))
            ).scalar_one_or_none()

            if row is None:
                if robux not in NEW:
                    raise SystemExit(f"{code} is not in NEW but does not exist — check the ladder")
                created.append(f"{code} ${_price(cost)} (закупка ${cost}, остаток {stock})")
                if not APPLY:
                    continue
                sku_id: str = await _create_sku(
                    session,
                    product_id=product_id,
                    robux=robux,
                    cost=cost,
                    stock=stock,
                    position=position,
                )
            else:
                sku_id = row.id
                # Keep the ladder readable after six insertions.
                if APPLY:
                    row.sort_order = position

            existing_map = (
                await session.execute(
                    select(SkuSupplierMapping.sku_id).where(
                        SkuSupplierMapping.sku_id == sku_id,
                        SkuSupplierMapping.supplier_slug == SUPPLIER,
                    )
                )
            ).first()
            if existing_map is None:
                mapped.append(f"{code} → g2b:{g2b_id}")
            if not APPLY:
                continue

            await upsert_mapping(
                session,
                MappingUpsert(
                    sku_id=sku_id,
                    supplier_slug=SUPPLIER,
                    kind="voucher",
                    external_product_id=g2b_id,
                    external_variant_id=None,
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by=ADMIN_ID,
                ),
            )

        if APPLY:
            await session.commit()

    _report(created, mapped)


def _report(created: list[str], mapped: list[str]) -> None:
    """Print what was done, or what would be. Split out for ruff's branch cap."""
    head = "ПРИМЕНЕНО" if APPLY else "ПРЕДПРОСМОТР (APPLY=1 чтобы применить)"
    print(f"=== {head} ===")
    print(f"новых SKU: {len(created)}")
    for line in created:
        print(f"  + {line}")
    print(f"новых маппингов на g2b: {len(mapped)}")
    for line in mapped:
        print(f"  + {line}")
    if APPLY:
        print("NEXT: страница бренда, затем «Сравнить поставщиков по бренду» в соурсинге.")
        print("NEXT: 2500 и 3000 дешевле у g2b, чем у nova, на которую они запинены.")


asyncio.run(main())
