"""Roblox gift cards on NOVA: four new denominations, nine mappings.

Run inside the api container:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-09-21_roblox_nova_cards.py

## What NOVA has that we did not

Their `roblox_global` category (`GET /api/v2/giftcards/cards`, read live
2026-09-21) carries nine denominations; we shelved five. The four missing ones
are **50, 100, 2500 and 3000 Robux** — the two cheapest, which no other
supplier of ours sells at all, and two middle rungs.

Cost and stock as read that day:

    50      $0.87873    10922
    100     $1.590588    5075
    800     $9.18        1069   (we had it, G2B $9.06)
    1000    $11.22        431   (we had it, G2B $11.40)
    2000    $22.44        227   (we had it, G2B $22.95)
    2500    $28.412916      9
    3000    $35.155524     99
    4500    $48.040266      8   (we had it, G2B $48.50)
    10000   $101.700324    29   (we had it, G2B $102.00)

NOVA is cheaper than G2B on four of the five we already sell, by fractions of
a percent — not a reason to reroute anything, and this seed reroutes nothing.

## Why the four new ones are forced to NOVA

`sourcing._pick_auto_mapping_slug` never auto-picks a `RESERVE_SUPPLIERS`
member, and NOVA is one. A NOVA-only SKU therefore resolves to no supplier at
all and its orders die with nothing to route to — the same trap the IMO import
hit a day earlier. Each new SKU gets `mode='force_supplier', supplier='nova'`,
which is exactly what the five existing Roblox SKUs already carry for G2B.

The five existing SKUs keep their G2B rule untouched. Their NOVA mapping is a
second source for the sourcing screen and an operator's switch, nothing more.

They are also the first SKUs in the catalogue with two active voucher
mappings, which is why the stock sweep had to learn to route before this seed
could run: 10000 Robux is at zero on G2B and twenty-nine on NOVA, and it is
pinned to G2B. Writing NOVA's count over it would have put a line we cannot
deliver back on the shelf.

## The adapter had to come first

Until the commit this seed ships with, `NovaFulfiller` could only call
`/api/v2/topups/order`, which requires player `fields` a gift card has none
of — so a voucher mapping would have refused every order with "no nova fields
could be built". The gift-card path (`_fulfill_giftcard`, verified against one
real $0.87873 purchase of `50_robux`, order `ord-1481455`) is what makes these
mappings mean anything.

Margin 14%, matching the four cheapest existing Roblox rungs, rounded to the
cent half-up — which is how the existing prices were arrived at. `b2b_markup_pct`
and `visible_b2b` are copied from the existing rungs rather than defaulted: 6%
and visible, not the catalogue-wide 7%.

Idempotent: an existing `sku_code` is skipped, mappings converge, rules upsert.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing.models import SkuSourcingRule

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
PRODUCT_SLUG = "roblox-robux-global"
CATEGORY = "roblox_global"
MARGIN = Decimal("14")
B2B_MARKUP = Decimal("6")

#: ``(robux, card_id, nova cost)`` — the full ladder, cheapest first. The five
#: we already sell are here too, because the mapping loop needs their card ids
#: and a partial list would be a second place to keep them in step.
LADDER: list[tuple[int, str, str]] = [
    (50, "50_robux", "0.878730"),
    (100, "100_robux", "1.590588"),
    (800, "800_robux", "9.180000"),
    (1000, "1000_robux", "11.220000"),
    (2000, "2000_robux", "22.440000"),
    (2500, "2500_robux", "28.412916"),
    (3000, "3000_robux", "35.155524"),
    (4500, "4500_robux", "48.040266"),
    (10000, "10000_robux", "101.700324"),
]

#: The ones we did not shelve before. Everything else already exists and is
#: only mapped here, never re-priced — their cost comes from G2B and the
#: hourly refresh owns it.
NEW = {50, 100, 2500, 3000}


def _price(cost: Decimal) -> Decimal:
    """Cost plus margin, to the cent, half-up — how the existing rungs round."""
    return (cost * (Decimal("1") + MARGIN / Decimal("100"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _force_nova(session: Any, sku_id: str) -> None:
    """Pin the SKU to NOVA. Without it a NOVA-only SKU routes nowhere."""
    row = (
        await session.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id))
    ).scalar_one_or_none()
    if row is None:
        session.add(
            SkuSourcingRule(
                sku_id=sku_id, mode="force_supplier", supplier_slug="nova", updated_by=ADMIN_ID
            )
        )
    else:
        row.mode, row.supplier_slug, row.updated_by = "force_supplier", "nova", ADMIN_ID


async def main() -> None:
    from yupay.modules.catalog import admin_schemas as cs
    from yupay.modules.catalog import admin_service as catalog

    factory = get_session_factory()
    async with factory() as session:
        product_id = (
            await session.execute(select(Product.id).where(Product.slug == PRODUCT_SLUG))
        ).scalar_one_or_none()
        if product_id is None:
            raise SystemExit(f"product {PRODUCT_SLUG} not found")

        created = mapped = forced = 0
        for position, (robux, card_id, cost_text) in enumerate(LADDER):
            code = f"roblox-{robux}"
            cost = Decimal(cost_text)
            row = (
                await session.execute(select(Sku).where(Sku.sku_code == code))
            ).scalar_one_or_none()

            if row is None:
                if robux not in NEW:
                    raise SystemExit(f"{code} is not in NEW but does not exist — check the ladder")
                sku = await catalog.create_sku(
                    session,
                    cs.SkuCreate(
                        product_id=product_id,
                        sku_code=code,
                        denomination=f"{robux} Robux",
                        region="GLOBAL",
                        price_usd=_price(cost),
                        cost_usdt=cost,
                        margin_percent=MARGIN,
                        sort_order=position,
                    ),
                )
                sku_id = sku.id
                # Copied from the existing rungs, not defaulted: this brand
                # sells to resellers at 6%, and the catalogue default is 7%.
                fresh = (await session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
                fresh.b2b_markup_pct = B2B_MARKUP
                fresh.visible_b2b = True
                created += 1
                await _force_nova(session, sku_id)
                forced += 1
            else:
                sku_id = row.id
                # Keep the ladder readable after four insertions.
                row.sort_order = position

            await upsert_mapping(
                session,
                MappingUpsert(
                    sku_id=sku_id,
                    supplier_slug="nova",
                    kind="voucher",
                    external_product_id=CATEGORY,
                    external_variant_id=card_id,
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by=ADMIN_ID,
                ),
            )
            mapped += 1

        await session.commit()

    print(f"новых SKU: {created} · маппингов на nova: {mapped} · правил force_supplier: {forced}")
    print("NEXT: проверить страницу бренда и закупки; цены новых рунгов — 14% над закупкой NOVA.")


asyncio.run(main())
