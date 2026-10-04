"""Pull the FazerCards «gift cards» that are not codes off the reseller shelf.

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-05_fzr_not_a_code.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-05_fzr_not_a_code.py

The 2026-10-05 voucher import took every FazerCards gift-card category as a
redeem code. The category notes say otherwise for nineteen of them:

* **FazerCards' own codes** — «Official FazerCards gift code… redeem at
  reseller.fazercards.com/redeem, enter your player ID»: a wrapper around the
  same top-up we already sell, gasped on their site. ``free_fire``,
  ``steam_cis``, ``telegram_stars``, ``telegram_premium``.
* **Direct top-ups** — «Enter your Riot ID», «Enter your TikTok username»,
  «Requires player Riot ID», «delivered directly to your account»: an order
  needs an identifier our voucher SKUs have no field for, so it would fail at
  the supplier. ``new_state_mobile_global``, ``wild_rift_{my,ph,sg}``,
  ``tiktok_*``, ``valorant_{au,ca,in,nz,tr}``.

Per affected SKU: the fzr mapping is deactivated and its «only fzr» rule
dropped. A SKU with another active supplier (G2B's Riot Cash for Valorant TR,
G2B's Telegram redeem codes) stays on sale and is re-priced to that supplier's
cost (``allow_price_drop=True`` — the fzr cost is gone, there is nothing to hold
the old price to). A SKU with no other supplier is deactivated; a brand with no
active SKU left is hidden from resellers (``visible_b2b = false``). Nothing is
deleted; idempotent.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import select, text
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Sku
from yupay.modules.integrations.cost_refresh import refresh_routed_cost
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing import service as sourcing
from yupay.modules.sourcing.models import SkuSourcingRule

APPLY = os.environ.get("APPLY") == "1"
NOT_A_CODE = {
    "free_fire", "steam_cis", "telegram_stars", "telegram_premium",
    "new_state_mobile_global", "wild_rift_my", "wild_rift_ph", "wild_rift_sg",
    "tiktok_ae", "tiktok_de", "tiktok_cn", "tiktok_id", "tiktok_it", "tiktok_jp",
    "valorant_au", "valorant_ca", "valorant_in", "valorant_nz", "valorant_tr",
}  # fmt: skip


async def affected() -> list[dict[str, Any]]:
    async with get_session_factory()() as db:
        rows = await db.execute(text("""
            select b.id brand_id, b.slug brand, s.id sku_id, s.sku_code, m.external_product_id cat,
                   (select count(*) from sku_supplier_mapping o
                     where o.sku_id = s.id and o.is_active and o.supplier_slug <> 'fzr') others
              from sku_supplier_mapping m
              join skus s on s.id = m.sku_id join products p on p.id = s.product_id
              join brands b on b.id = p.brand_id
             where m.supplier_slug = 'fzr' and m.kind = 'voucher' and m.is_active
               and m.external_product_id = any(:cats)
             order by b.slug, s.sort_order
        """), {"cats": sorted(NOT_A_CODE)})  # fmt: skip
        return [dict(r) for r in rows.mappings().all()]


async def fix_sku(row: dict[str, Any]) -> str:
    async with get_session_factory()() as db, db.begin():
        mapping = await db.get(SkuSupplierMapping, (row["sku_id"], "fzr"))
        if mapping is not None:
            mapping.is_active = False
        rule = (
            await db.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == row["sku_id"]))
        ).scalar_one_or_none()
        if rule is not None and rule.supplier_slug == "fzr":
            await sourcing.delete_rule(db, row["sku_id"])
        if row["others"] == 0:
            sku = await db.get(Sku, row["sku_id"])
            if sku is not None:
                sku.active = False
            return "off"
    outcome = await _reprice(row["sku_id"])
    return f"re-routed ({outcome})"


async def _reprice(sku_id: str) -> str:
    async with get_session_factory()() as db, db.begin():
        try:
            out = await refresh_routed_cost(db, sku_id=sku_id, allow_price_drop=True)
        except Exception as exc:  # noqa: BLE001 -- the route change stands; the hourly pass re-prices
            return f"цена не пересчитана: {exc!s:.60}"
        return (
            f"{out.source}: {out.old_cost}→{out.new_cost}" if out.updated else str(out.reason)[:60]
        )


async def hide_empty_brands(brand_ids: set[str]) -> list[str]:
    hidden = []
    async with get_session_factory()() as db, db.begin():
        for brand_id in brand_ids:
            alive = await db.execute(text("""
                select count(*) from skus s join products p on p.id = s.product_id
                 where p.brand_id = :b and s.active
            """), {"b": brand_id})  # fmt: skip
            if alive.scalar_one() == 0:
                brand = await db.get(Brand, brand_id)
                if brand is not None and brand.visible_b2b:
                    brand.visible_b2b = False
                    hidden.append(brand.slug)
    return hidden


async def main() -> None:
    rows = await affected()
    print(f"SKU с fzr-«кодом», который не код: {len(rows)}")
    by_brand: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_brand.setdefault(r["brand"], []).append(r)
    for brand, rs in by_brand.items():
        keep = sum(1 for r in rs if r["others"])
        print(f"  {brand:32s} {len(rs):3d} SKU, остаются через другого поставщика: {keep}")
    if not APPLY:
        print("APPLY не задан — ничего не записано.")
        return
    for r in rows:
        print(f"  {r['sku_code']:48s} {await fix_sku(r)}")
    hidden = await hide_empty_brands({r["brand_id"] for r in rows})
    print(f"Скрыто брендов без живых SKU: {len(hidden)}: {', '.join(sorted(hidden))}")


if __name__ == "__main__":
    asyncio.run(main())
