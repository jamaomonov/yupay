"""Telegram Premium: a second channel on G2B.

The three Premium SKUs reached G-Engine only. G2B sells the same three as a
**direct top-up** under its `Telegram` game — not the "Redeem Code" vouchers
sitting beside them in its catalogue, which are a different product — and
does it cheaper on every tier: $12.23 / $16.31 / $29.57 against the
$12.8413 / $17.1253 / $31.0483 we pay G-Engine today.

**Routing does not change, on purpose.** Among non-reserve suppliers
`sourcing._pick_supplier` keeps the *oldest* active mapping, and G-Engine's
is older, so every order still goes where it goes today. Moving them is an
operator decision on the brand's sourcing screen, and it is worth making
deliberately: `cost_usdt` below is G-Engine's and stays theirs until the
route actually moves, because the merchant price list is cost-plus and
computed live.

G2B's variant is the catalogue **name**, verbatim — the same convention
`whiteout_survival:9999` and `mcgg_ru:Battle for Discounts` follow, and what
`catalog_watch` matches against `games_catalogue`.

Dry run by default:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-09-20_telegram_premium_g2b.py

Then commit it:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-09-20_telegram_premium_g2b.py
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

APPLY = os.environ.get("APPLY") == "1"

G2B_GAME = "Telegram"

#: our sku_code -> G2B's denomination name, exactly as `games_catalogue`
#: spells it (lowercase "premium" is theirs, not a typo).
PREMIUM = {
    "tg-premium-3m": "3 months premium",
    "tg-premium-6m": "6 months premium",
    "tg-premium-12m": "12 months premium",
}


async def main() -> None:
    async with get_session_factory()() as db:
        rows = (
            (await db.execute(select(Sku).where(Sku.sku_code.in_(list(PREMIUM))))).scalars().all()
        )
        found = {s.sku_code for s in rows}
        for missing in sorted(set(PREMIUM) - found):
            print(f"!! {missing} not found — skipped")

        for sku in sorted(rows, key=lambda s: s.sku_code):
            variant = PREMIUM[sku.sku_code]
            print(f"map g2b  {sku.sku_code:<16} {sku.denomination:<12} -> {G2B_GAME}:{variant}")
            if not APPLY:
                continue
            await upsert_mapping(
                db,
                MappingUpsert(
                    sku_id=sku.id,
                    supplier_slug="g2b",
                    kind="game",
                    external_product_id=G2B_GAME,
                    external_variant_id=variant,
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by="tg-premium-g2b-2026-09-20",
                ),
            )

        if APPLY:
            await db.commit()
            print(f"\nwrote {len(rows)} mappings")
        else:
            print(f"\ndry run — {len(rows)} mappings would be written")


if __name__ == "__main__":
    asyncio.run(main())
