"""Mapping review fixes before Valorant, LoL, Fortnite, CoD Mobile, FC 26 and PUBG go retail.

Run inside the api container (read-modify-write, idempotent):

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-11-25_storefront5_mapping_fixes.py

Set ``DRY_RUN=1`` to print the plan and roll back.

Found by the 2026-11-25 review of supplier catalogues against our SKUs:

1. ``fortnite-us-150-usd`` costs $379 720: FazerCards' own catalogue carries that
   price (it grew ~6 % an hour on 2026-11-09). Switched off until they fix it.
2. ``wild-rift-wc-eu`` sells «2025 WC» but is mapped to FazerCards' 3275 WC offer,
   at the 3275 WC price — the label was wrong, not the mapping. Renamed.
3. A second supplier the catalogue already lists, matched rung by rung on the VP /
   points count: FazerCards for Valorant TR, AU and NZ; G-Engine for Valorant RU
   325 VP; FazerCards for FC 26 Points (on the G-Engine brand) and G2B for PUBG
   G-Coins (on the FazerCards brand) — the same products had been imported twice
   as two brands, one supplier each.
4. Rungs a supplier sells and we never listed: Valorant EU 1520 and 8700 VP
   (G-Engine), AU 1750 VP and NZ 325 and 3550 VP (FazerCards). Cost from the
   catalogue, margin and B2B visibility from the brand's siblings. G-Engine's RU
   75 VP ($3.50) and 1725 VP ($20) are skipped by ``fair``: a VP there costs more
   than 20 % over the brand's median — nobody should be sold those.

Every new or added mapping is re-priced through the hourly refresh path, and a
rule with two or more suppliers is handed to smart routing (``managed``).
"""

from __future__ import annotations

import asyncio
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import yupay.api.v1  # noqa: F401 -- loads every mapper in the right order
from sqlalchemy import select, text
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cat_schemas
from yupay.modules.catalog import admin_service as catalog
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.cost_refresh import refresh_sku_cost_for_mapping
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing.models import SkuSourcingRule

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
DRY_RUN = os.environ.get("DRY_RUN") == "1"

#: (our brand, supplier, catalogue parent id) — map every catalogue rung whose
#: number matches one of the brand's SKUs; with ``create`` also list the rest.
ADD: list[tuple[str, str, str, bool]] = [
    ("valorant-vp-tr", "fzr", "valorant_tr", False),
    ("valorant-vp-au", "fzr", "valorant_au", True),
    ("valorant-vp-nz", "fzr", "valorant_nz", True),
    ("valorant-vp-ru", "gengine", "36", True),
    ("valorant-vp-eu", "gengine", "79", True),
]
#: (target brand, source brand) — copy the source SKUs' mappings onto the target
#: SKU with the same number (same product imported twice).
COPY: list[tuple[str, str]] = [
    # FC 26 is NOT here any more: G-Engine's card is Xbox, FazerCards' is EA app (PC)
    # — two products, not one imported twice. 2026-11-25_fc26_split_platforms.sql
    # undoes the copy this script made on its first run.
    ("pubg-battlegrounds", "pubg-g-coins"),
]


def number(label: str | None) -> int | None:
    """The amount a rung delivers: «120 TRY (375 VP)» → 375, «2800 FC Points» →
    2800, «PUBG G Coins - 510» → 510, «510 G» → 510."""
    if not label:
        return None
    m = re.search(r"\(([\d.,]+)\s*VP\)", label) or re.search(
        r"([\d][\d.,]*)\s*(VP|FC Points|G-Coin|G\b|WC)", label
    )
    if m is None:
        m = re.search(r"-\s*([\d][\d.,]*)\s*$", label)
    return int(m.group(1).replace(",", "").split(".")[0]) if m else None


def fair(skus: list[Sku], n: int, cost: Decimal) -> bool:
    """A new rung is listed only if a VP costs at most 20 % above the brand's median —
    G-Engine's RU 75 VP at $3.50 (240 VP sells at $2.93) is a rung nobody should buy."""
    per = sorted(
        s.cost_usdt / number(s.denomination) for s in skus if s.cost_usdt and number(s.denomination)
    )
    if not per:
        return True
    median = per[len(per) // 2]
    return cost / n <= median * Decimal("1.2")


async def brand_skus(db: Any, slug: str) -> list[Sku]:
    return list(
        (
            await db.execute(
                select(Sku)
                .join(Product, Product.id == Sku.product_id)
                .join(Brand, Brand.id == Product.brand_id)
                .where(Brand.slug == slug, Sku.active.is_(True))
            )
        )
        .scalars()
        .all()
    )


async def add_mapping(
    db: Any, sku: Sku, *, slug: str, kind: str, parent: str, variant: str
) -> None:
    print(f"  map {sku.sku_code} ← {slug}:{parent}/{variant}")
    if DRY_RUN:
        return
    await upsert_mapping(
        db,
        MappingUpsert(
            sku_id=sku.id,
            supplier_slug=slug,
            kind=kind,
            external_product_id=parent,
            external_variant_id=variant,
            quantity=1,
            extra={},
            is_active=True,
            updated_by=ADMIN_ID,
        ),
    )
    mapping = await db.get(SkuSupplierMapping, (sku.id, slug))
    await refresh_sku_cost_for_mapping(db, mapping=mapping, allow_price_drop=False)


async def new_sku(
    db: Any, sibling: Sku, *, brand: str, label: str, cost: Decimal, position: int
) -> Sku | None:
    code = f"{brand}-{label.lower().replace(' ', '-')}"
    margin = sibling.margin_percent or Decimal("13")
    price = (cost * (1 + margin / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    print(f"  new {code} «{label}» cost {cost} price {price}")
    if DRY_RUN:
        return None
    sku = await catalog.create_sku(
        db,
        cat_schemas.SkuCreate(
            product_id=sibling.product_id,
            sku_code=code,
            denomination=label,
            price_usd=price,
            cost_usdt=cost,
            margin_percent=margin,
            sort_order=position,
        ),
    )
    row = await db.get(Sku, sku.id)
    row.visible_b2b = sibling.visible_b2b
    row.b2b_markup_pct = sibling.b2b_markup_pct
    return row


async def sync_rule(db: Any, sku_id: str, fallback_supplier: str) -> None:
    """A routed rule for every touched SKU; two suppliers or more → managed."""
    if DRY_RUN:
        return
    suppliers = (
        (
            await db.execute(
                select(SkuSupplierMapping.supplier_slug).where(
                    SkuSupplierMapping.sku_id == sku_id, SkuSupplierMapping.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    rule = await db.get(SkuSourcingRule, sku_id)
    if rule is None:
        db.add(
            SkuSourcingRule(
                sku_id=sku_id,
                mode="force_supplier",
                supplier_slug=fallback_supplier,
                managed=len(suppliers) >= 2,
                updated_by=ADMIN_ID,
            )
        )
    elif rule.mode == "force_supplier" and len(suppliers) >= 2:
        rule.managed = True


async def main() -> None:  # noqa: PLR0912 -- a one-off seed reads top to bottom
    async with get_session_factory()() as db:
        # 1. the runaway price
        off = (
            await db.execute(select(Sku).where(Sku.sku_code == "fortnite-us-150-usd"))
        ).scalar_one_or_none()
        if off is not None and off.active:
            print("off fortnite-us-150-usd")
            if not DRY_RUN:
                off.active = False
        # 2. the mislabelled rung
        for sku in await brand_skus(db, "wild-rift-wc-eu"):
            if sku.denomination == "2025 WC":
                print(f"rename {sku.sku_code}: 2025 WC → 3275 WC")
                if not DRY_RUN:
                    sku.denomination = "3275 WC"
        # 3–4. catalogue rungs
        for brand, slug, parent, create in ADD:
            print(f"{brand} ← {slug}:{parent}")
            skus = await brand_skus(db, brand)
            by_num = {number(s.denomination): s for s in skus}
            rows = (
                await db.execute(
                    text(
                        "SELECT kind, external_id, title, price_usdt FROM supplier_catalog_cache"
                        " WHERE supplier_slug = :s AND parent_external_id = :p"
                        " AND kind LIKE '%_denom'"
                    ),
                    {"s": slug, "p": parent},
                )
            ).all()
            position = max((s.sort_order for s in skus), default=0) + 1
            for kind, ext, title, price in rows:
                n = number(title)
                target = by_num.get(n)
                if target is not None:
                    have = await db.get(SkuSupplierMapping, (target.id, slug))
                    if have is None or not have.is_active:
                        await add_mapping(
                            db,
                            target,
                            slug=slug,
                            kind=kind.removesuffix("_denom"),
                            parent=parent,
                            variant=ext,
                        )
                        await sync_rule(db, target.id, slug)
                elif create and n and price and skus:
                    if not fair(skus, n, Decimal(price)):
                        print(f"  skip {n} VP at {price}: dearer per VP than the brand's rungs")
                        continue
                    created = await new_sku(
                        db,
                        skus[0],
                        brand=brand,
                        label=f"{n} VP",
                        cost=Decimal(price),
                        position=position,
                    )
                    position += 1
                    if created is not None:
                        await add_mapping(
                            db,
                            created,
                            slug=slug,
                            kind=kind.removesuffix("_denom"),
                            parent=parent,
                            variant=ext,
                        )
                        await sync_rule(db, created.id, slug)
        # 3b. the same product imported twice: copy mappings across
        for target_brand, source_brand in COPY:
            print(f"{target_brand} ← mappings of {source_brand}")
            targets = {number(s.denomination): s for s in await brand_skus(db, target_brand)}
            for src in await brand_skus(db, source_brand):
                tgt = targets.get(number(src.denomination))
                if tgt is None:
                    print(f"  no match for {src.sku_code} «{src.denomination}»")
                    continue
                for m in (
                    (
                        await db.execute(
                            select(SkuSupplierMapping).where(
                                SkuSupplierMapping.sku_id == src.id,
                                SkuSupplierMapping.is_active.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                ):
                    have = await db.get(SkuSupplierMapping, (tgt.id, m.supplier_slug))
                    if have is not None and have.is_active:
                        continue
                    await add_mapping(
                        db,
                        tgt,
                        slug=m.supplier_slug,
                        kind=m.kind,
                        parent=m.external_product_id,
                        variant=m.external_variant_id or "",
                    )
                    await sync_rule(db, tgt.id, m.supplier_slug)
        if DRY_RUN:
            await db.rollback()
            print("dry run — rolled back")
        else:
            await db.commit()
            print("committed")


asyncio.run(main())
