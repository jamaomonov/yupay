"""Turn on the G2B player check for the bulk-imported brands where it is real.

Run after ``2026-10-04_bulk_topup_import.py``, inside the api container:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_player_check.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_player_check.py

G2B's ``checkPlayerId`` exists for every game, but for some it checks nothing:
it answers ``{"valid": "valid", "name": "No validation required"}`` (Genshin,
Honkai: Star Rail, ZZZ, IMO, SoulChill on 2026-10-04), and a few accept any id
outright (Zepeto, Oxide). A check that confirms garbage is worse than none —
the customer sees a green tick on a typo. So each game is asked about an id
that cannot exist, and the check is switched on only where G2B says
``invalid``. Anything else — ``No validation required``, ``valid``, an error —
leaves the brand without one, and the list is printed.

The probe cannot prove the opposite failure (a validator that rejects every
id): that needs a real player id, which a brand nobody has bought from does
not have. Watch the first week's verdicts per brand; a brand answering only
``invalid`` gets its check switched off by hand.

Scope: brands whose mappings carry ``updated_by = 'bulk-topup-import'`` and
exactly one active G2B game (``player_check.resolve_g2b_game_code`` refuses a
brand spanning two). The check rides the ``player_id`` field of every product
in the brand (ADR-0079: brand-scoped, all products must agree), with
``server_field = "server"`` when the form has one. Idempotent.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Product
from yupay.modules.fulfillment.suppliers import REGISTRY

APPLY = os.environ.get("APPLY") == "1"
#: Ten digits, no game issues it as a real account in any region we probed.
BOGUS_ID = "9081726354"
BOGUS_SERVER = "1001"


async def brands() -> list[dict[str, Any]]:
    """Bulk-imported brands with their one G2B game code and product ids."""
    async with get_session_factory()() as db:
        rows = await db.execute(text("""
            select b.slug,
                   array_agg(distinct m.external_product_id)
                     filter (where m.supplier_slug = 'g2b' and m.is_active and m.kind = 'game') g2b,
                   array_agg(distinct p.id::text) products
              from brands b join products p on p.brand_id = b.id
              join skus s on s.product_id = p.id
              join sku_supplier_mapping m on m.sku_id = s.id
             where b.id in (select p2.brand_id from products p2 join skus s2 on s2.product_id = p2.id
                            join sku_supplier_mapping m2 on m2.sku_id = s2.id
                            where m2.updated_by = 'bulk-topup-import')
             group by b.slug order by b.slug
        """))  # fmt: skip
        return [dict(r) for r in rows.mappings().all()]


async def probe(code: str, with_server: bool) -> str:
    """``real``, ``noval``, ``accepts-any`` or ``error`` for one G2B game."""
    client = REGISTRY["g2b"]._client()
    try:
        r = await client.games_check_player(
            game_code=code,
            player_id=BOGUS_ID,
            server_id=BOGUS_SERVER if with_server else None,
            charname=None,
        )
    except Exception:  # noqa: BLE001 -- an outage is "do not enable", not a crash
        return "error"
    finally:
        await asyncio.sleep(0.4)
    if "no validation" in str(r.get("name") or "").lower():
        return "noval"
    return "accepts-any" if str(r.get("valid")).lower() == "valid" else "real"


async def enable(product_ids: list[str]) -> None:
    async with get_session_factory()() as db, db.begin():
        for pid in product_ids:
            product = await db.get(Product, pid)
            if product is None:
                continue
            fields = [dict(f) for f in product.required_fields or []]
            has_server = any(f.get("key") == "server" for f in fields)
            for f in fields:
                if f.get("key") == "player_id":
                    f["check"] = {
                        "provider": "g2b",
                        "server_field": "server" if has_server else None,
                    }
            product.required_fields = fields
            flag_modified(product, "required_fields")


async def main() -> None:
    verdicts: dict[str, list[str]] = {}
    for b in await brands():
        codes = [c for c in (b["g2b"] or []) if c]
        if len(codes) != 1:
            verdicts.setdefault("no-single-g2b-game" if codes else "no-g2b", []).append(b["slug"])
            continue
        async with get_session_factory()() as db:
            form = (await db.get(Product, b["products"][0])).required_fields or []  # type: ignore[union-attr]
        kind = await probe(codes[0], any(f.get("key") == "server" for f in form))
        verdicts.setdefault(kind, []).append(b["slug"])
        if kind == "real" and APPLY:
            await enable(b["products"])
    for kind, slugs in sorted(verdicts.items()):
        print(f"{kind}: {len(slugs)}")
        if kind != "real":
            print("   " + ", ".join(slugs))
    print("Записано." if APPLY else "APPLY не задан — ничего не записано.")


if __name__ == "__main__":
    asyncio.run(main())
