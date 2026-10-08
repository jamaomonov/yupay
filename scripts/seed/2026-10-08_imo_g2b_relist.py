"""IMO after G2B replaced its diamond ladder (2026-10-08).

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-08_imo_g2b_relist.py

G2B wrote on 2026-10-08: "We've added some new denominations for IMO TopUp."
What actually happened, read live from ``games_catalogue('imo')``:

    before (2026-09-20):  200, 500, 1000, 2000, 5000          — names "200 Diamonds" …
    now    (2026-10-08):  10, 50, 100, 160, 210, 420, 840,    — names "10", "50" …
                          1680, 2100, 4200, 8400, 16800, 21000

The old five are gone, not kept; the new thirteen are the NOVA/fzr ladder plus
50, 160 and 210, and the catalogue names are bare numbers now. Per diamond G2B
quotes ~$0.01847 against fzr's $0.01945 (snapshot 2026-09-24) — about 5 %
cheaper at every shared rung.

Three consequences, and this script is all three:

1. **``imo-200/500/1000/2000/5000`` are dead.** Their only mapping points at a
   G2B catalogue name that no longer exists; an order would fail at
   fulfilment. The catalogue watch already marked them ``catalog_missing_since``
   on its 12:19 tick and would deactivate them on the second strike — this
   does it now, explicitly, and deactivates the mapping too so the watch stops
   remembering a position G2B replaced rather than paused. Not one of the five
   ever sold.

2. **The ten shared rungs get a G2B mapping and move to ``auto`` routing.**
   They are ``force_supplier fzr`` today (2026-09-24, when fzr took over from
   NOVA). fzr and NOVA are reserve suppliers (ADR-0081), so ``auto`` resolves
   to G2B — the one non-reserve mapping — and the two reserves stay reachable
   by the same explicit ``force_supplier`` decision as before. The route change
   re-prices through ``refresh_routed_cost(allow_price_drop=False)``, which is
   the owner's rule for a cheaper supplier: shelf price unchanged, margin
   widens (ADR-0091).

3. **50, 160 and 210 are added.** 160 and 210 were dropped on 2026-09-20
   because they sat either side of G2B's 200 and read as the worse deal next
   to it; 200 is gone, so the objection is gone with it. Margin 14 %, the
   figure the neighbouring rungs carry.

Everything G2B-side uses the bare-number catalogue name, byte for byte —
``external_variant_id`` is what ``create_game_order`` sends as
``catalogue_name`` and what the catalogue watch compares against.

``DRY_RUN=1`` runs everything (supplier quotes included) and rolls back.

Idempotent: mappings and rules converge, existing SKUs are skipped, and the
re-sort rewrites the ladder it already has.
"""

from __future__ import annotations

import asyncio
import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import yupay.main  # noqa: F401  — registers every ORM model before the first query
from sqlalchemy import select, update
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.cost_refresh import refresh_routed_cost
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing.service import set_rule

BRAND_SLUG = "imo"
PRODUCT_SLUG = "imo-diamonds"
G2B_GAME_CODE = "imo"
ADMIN_ID = "00000000-0000-7000-8000-000000000001"
NEW_MARGIN_PERCENT = Decimal("14")

#: Gone from G2B's catalogue; nothing else sells them.
DEAD: list[str] = ["imo-200", "imo-500", "imo-1000", "imo-2000", "imo-5000"]

#: Our existing fzr/NOVA rungs that G2B now sells too. (amount, G2B name).
SHARED: list[tuple[int, str]] = [
    (10, "10"),
    (100, "100"),
    (420, "420"),
    (840, "840"),
    (1680, "1680"),
    (2100, "2100"),
    (4200, "4200"),
    (8400, "8400"),
    (16800, "16800"),
    (21000, "21000"),
]

#: Rungs G2B sells and we did not. (amount, G2B name, G2B cost 2026-10-08).
NEW: list[tuple[int, str, str]] = [
    (50, "50", "0.928"),
    (160, "160", "2.978"),
    (210, "210", "3.907"),
]


def _sku_code(amount: int) -> str:
    return f"imo-{amount}"


def _denomination(amount: int) -> str:
    return f"{amount} Diamonds"


def _sell_price(cost: Decimal) -> Decimal:
    """The same formula ``integrations.service._sell_price`` uses."""
    return (cost * (Decimal(1) + NEW_MARGIN_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _product_id(session: Any) -> str:
    brand_id = (
        await session.execute(select(Brand.id).where(Brand.slug == BRAND_SLUG))
    ).scalar_one()
    return str(
        (
            await session.execute(
                select(Product.id).where(Product.brand_id == brand_id, Product.slug == PRODUCT_SLUG)
            )
        ).scalar_one()
    )


async def _sku_id(session: Any, code: str) -> str | None:
    row = (await session.execute(select(Sku.id).where(Sku.sku_code == code))).scalar_one_or_none()
    return None if row is None else str(row)


async def _g2b_mapping(session: Any, *, sku_id: str, name: str) -> None:
    await upsert_mapping(
        session,
        MappingUpsert(
            sku_id=sku_id,
            supplier_slug="g2b",
            kind="game",
            external_product_id=G2B_GAME_CODE,
            external_variant_id=name,
            quantity=1,
            extra={},
            is_active=True,
            updated_by=ADMIN_ID,
        ),
    )


async def _retire_dead(session: Any) -> list[str]:
    done: list[str] = []
    for code in DEAD:
        sku_id = await _sku_id(session, code)
        if sku_id is None:
            continue
        await session.execute(update(Sku).where(Sku.id == sku_id).values(active=False))
        await session.execute(
            update(SkuSupplierMapping)
            .where(SkuSupplierMapping.sku_id == sku_id, SkuSupplierMapping.supplier_slug == "g2b")
            .values(is_active=False, updated_by=ADMIN_ID)
        )
        done.append(code)
    return done


async def _reroute_shared(session: Any) -> list[str]:
    lines: list[str] = []
    for amount, name in SHARED:
        code = _sku_code(amount)
        sku_id = await _sku_id(session, code)
        if sku_id is None:
            lines.append(f"{code}: missing, skipped")
            continue
        await _g2b_mapping(session, sku_id=sku_id, name=name)
        await set_rule(session, sku_id=sku_id, mode="auto", supplier_slug=None, admin_id=ADMIN_ID)
        # Same call the rule endpoint makes: the route moved, so the cost
        # follows it; the shelf price does not drop (ADR-0091).
        out = await refresh_routed_cost(session, sku_id=sku_id, allow_price_drop=False)
        lines.append(
            f"{code}: route auto→g2b, cost {out.old_cost}→{out.new_cost}, "
            f"price {out.old_price}→{out.new_price}"
            f"{' (' + out.reason + ')' if out.reason else ''}"
        )
    return lines


async def _add_new(session: Any, *, product_id: str) -> list[str]:
    from yupay.modules.catalog import admin_schemas as catalog_schemas
    from yupay.modules.catalog import admin_service as catalog

    lines: list[str] = []
    for amount, name, cost in NEW:
        code = _sku_code(amount)
        sku_id = await _sku_id(session, code)
        if sku_id is None:
            sku = await catalog.create_sku(
                session,
                catalog_schemas.SkuCreate(
                    product_id=product_id,
                    sku_code=code,
                    denomination=_denomination(amount),
                    price_usd=_sell_price(Decimal(cost)),
                    cost_usdt=Decimal(cost),
                    margin_percent=NEW_MARGIN_PERCENT,
                ),
            )
            sku_id = str(sku.id)
            lines.append(f"{code}: created, ${_sell_price(Decimal(cost))} (cost {cost})")
        else:
            lines.append(f"{code}: exists, mapping converged")
        await _g2b_mapping(session, sku_id=sku_id, name=name)
    return lines


async def _order_by_price(session: Any, product_id: str) -> int:
    """One ascending ladder; retired rungs sink to the end."""
    skus = (
        (
            await session.execute(
                select(Sku)
                .where(Sku.product_id == product_id)
                .order_by(Sku.active.desc(), Sku.price_usd)
            )
        )
        .scalars()
        .all()
    )
    for i, sku in enumerate(skus):
        await session.execute(update(Sku).where(Sku.id == sku.id).values(sort_order=i))
    return len(skus)


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        product_id = await _product_id(session)
        retired = await _retire_dead(session)
        rerouted = await _reroute_shared(session)
        added = await _add_new(session, product_id=product_id)
        ordered = await _order_by_price(session, product_id)
        if os.environ.get("DRY_RUN"):
            await session.rollback()
            print("DRY_RUN: rolled back")
        else:
            await session.commit()

    print(f"retired  {retired}")
    for line in rerouted:
        print(f"shared   {line}")
    for line in added:
        print(f"new      {line}")
    print(f"ladder   {ordered} SKUs ordered by price (retired last)")


asyncio.run(main())
