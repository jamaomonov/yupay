"""Telegram Stars and Premium: a channel on NOVA's Fragment API.

Both brands reached G-Engine only, and Premium now also G2B. NOVA is cheaper
than either on every line we checked on 2026-09-20 — Premium $12.1699 /
$16.2299 / $29.4249 against G-Engine's $12.8413 / $17.1253 / $31.0483, and a
Star at $0.015225 against $0.015455 — and it is the **only** supplier that
sells Stars by free amount, which is the line the storefront actually uses.

Routing does not change: NOVA is a reserve (ADR-0081) and is never picked
automatically. These mappings make it reachable by an explicit
`force_supplier`, and — because only g2b and nova have a `cost_lookup` — they
are what lets the sourcing screen show a live Telegram price at all.

The mapping shape mirrors G-Engine's, because `quantity_for` reads both:

* `fragment-stars` carries the pack size in `quantity` and no variant. The
  free-amount line carries `1`, and the customer's own count arrives as
  `item.qty`.
* `fragment-premium` carries the months as its variant — the only thing
  separating its three products.

Dry run by default:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-09-20_telegram_nova_fragment.py

Then commit it:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-09-20_telegram_nova_fragment.py
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.models import NOVA_FRAGMENT_PREMIUM, NOVA_FRAGMENT_STARS
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

APPLY = os.environ.get("APPLY") == "1"

#: sku_code -> months
PREMIUM = {"tg-premium-3m": "3", "tg-premium-6m": "6", "tg-premium-12m": "12"}

#: sku_code -> the mapping ``quantity`` `quantity_for` multiplies by. The
#: free-amount line is 1 on purpose; every package is its own pack size.
STARS = {
    "tg-stars-any": 1,
    "tg-stars-50": 50,
    "tg-stars-75": 75,
    "tg-stars-100": 100,
    "tg-stars-150": 150,
    "tg-stars-250": 250,
    "tg-stars-350": 350,
    "tg-stars-500": 500,
    "tg-stars-750": 750,
    "tg-stars-1000": 1000,
    "tg-stars-1500": 1500,
    "tg-stars-2500": 2500,
}


async def main() -> None:
    async with get_session_factory()() as db:
        codes = list(PREMIUM) + list(STARS)
        skus = {
            s.sku_code: s
            for s in (await db.execute(select(Sku).where(Sku.sku_code.in_(codes)))).scalars().all()
        }
        for missing in sorted(set(codes) - set(skus)):
            print(f"!! {missing} not found — skipped")

        written = 0
        for code, months in PREMIUM.items():
            sku = skus.get(code)
            if sku is None:
                continue
            print(f"map nova {code:<16} -> {NOVA_FRAGMENT_PREMIUM}:{months} (months)")
            written += 1
            if APPLY:
                await upsert_mapping(
                    db,
                    MappingUpsert(
                        sku_id=sku.id,
                        supplier_slug="nova",
                        kind="game",
                        external_product_id=NOVA_FRAGMENT_PREMIUM,
                        external_variant_id=months,
                        quantity=1,
                        extra={},
                        is_active=True,
                        updated_by="tg-nova-fragment-2026-09-20",
                    ),
                )

        for code, pack in STARS.items():
            sku = skus.get(code)
            if sku is None:
                continue
            print(f"map nova {code:<16} -> {NOVA_FRAGMENT_STARS} (quantity={pack})")
            written += 1
            if APPLY:
                await upsert_mapping(
                    db,
                    MappingUpsert(
                        sku_id=sku.id,
                        supplier_slug="nova",
                        kind="game",
                        external_product_id=NOVA_FRAGMENT_STARS,
                        external_variant_id=None,
                        quantity=pack,
                        extra={},
                        is_active=True,
                        updated_by="tg-nova-fragment-2026-09-20",
                    ),
                )

        if APPLY:
            await db.commit()
            print(f"\nwrote {written} mappings")
        else:
            print(f"\ndry run — {written} mappings would be written")


if __name__ == "__main__":
    asyncio.run(main())
