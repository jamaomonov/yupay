"""Backfill NOVA and G-Engine mappings for SKUs that only have G2B.

Every SKU already carries at least one mapping, but coverage is lopsided:
G2B 214, NOVA 42, G-Engine 21. Where a supplier sells the very same
denomination we do, a mapping should exist — it is what `force_supplier`
and the NOVA fallback need to have a second channel at all.

**Why this is safe to run.** A new mapping cannot take an order away from
whoever serves it today. `sourcing._pick_supplier` skips reserve suppliers
outright (NOVA, ADR-0081) and among the rest picks the *oldest* active
mapping, so anything written here is by construction newer than the
incumbent. The one case that would move traffic — a SKU with no active
non-reserve mapping — does not arise: the ten Free Fire SKUs in that shape
carry an explicit `force_supplier: nova` rule already.

**Matching rule: exact, or nothing.** Titles are compared after
lowercasing and collapsing everything non-alphanumeric to single spaces.
Anything short of equality is reported, never mapped. Trigram similarity
was tried first and is not usable here — on our own data it ranked
`mobile_legends_ru` above `mobile_legends_global` for the *global* brand,
and `honkai_star_rail_us` above `_global`. A wrong region is a top-up
delivered to an account that cannot receive it, so the region is decided
below by hand and only the denomination is matched by machine.

Dry run by default, same shape as the other scripts here:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-09-19_backfill_nova_gengine_mappings.py

Then commit it:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-09-19_backfill_nova_gengine_mappings.py
"""

from __future__ import annotations

import asyncio
import os
import re

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.catalog_sync import run_game_denomination_sync
from yupay.modules.integrations.models import (
    RESERVE_SUPPLIERS,
    SkuSupplierMapping,
    SupplierCatalogCache,
)
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

APPLY = os.environ.get("APPLY") == "1"

# brand slug -> supplier game id. Region picked by hand against `skus.region`;
# see the module docstring for why this is not left to string similarity.
PAIRS: dict[str, dict[str, str]] = {
    "pubg-mobile": {"nova": "pubg_mobile_auto", "gengine": "8"},
    "mobile-legends": {"nova": "mobile_legends_global", "gengine": "44"},
    "mobile-legends-ru": {"nova": "mobile_legends_ru", "gengine": "5"},
    "delta-force": {"nova": "delta_force", "gengine": "9"},
    "free-fire": {"nova": "free_fire_cis"},
    "arena-breakout": {"nova": "arena_breakout", "gengine": "13"},
    "arena-breakout-infinite": {"nova": "arena_breakout_infinite"},
    "magic-chess-gogo": {"nova": "magic_chess_gogo_global", "gengine": "38"},
    "magic-chess-gogo-ru": {"nova": "magic_chess_gogo_ru", "gengine": "66"},
    "blood-strike": {"nova": "blood_strike", "gengine": "25"},
    "whiteout-survival": {"nova": "whiteout_survival"},
    "genshin-impact": {"nova": "genshin_impact_global", "gengine": "11"},
    "honkai-star-rail": {"nova": "honkai_star_rail_global", "gengine": "10"},
    "oxide-survival-island": {"nova": "oxide_survival_island"},
}

# Deliberately absent, each for a reason rather than an oversight:
#   free-fire / gengine 46  — our brand is the CIS server; G-Engine lists one
#                             undifferentiated "Garena Free Fire".
#   roblox / gengine 80     — "Roblox Gamepass" is a different product from the
#                             Robux top-up we sell.
#   arena-breakout-infinite / gengine 13 — "Arena Breakout" is the mobile title;
#                             Infinite is the separate PC game.
# NOVA lists nothing for roblox, standoff-2, discord or the Telegram brands.


def norm(text: str) -> str:
    """Lowercase, and collapse every run of non-alphanumerics to one space."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


#: "1980 + 260 genesis crystals" -> (1980, 260, "genesis crystals");
#: "60 genesis crystals" -> (60, None, "genesis crystals").
_AMOUNT = re.compile(r"^(\d+)(?:\s*\+\s*(\d+))?\s+(.+)$")


def amount_key(text: str) -> tuple[int, str] | None:
    """Total units and unit name, or ``None`` when the title is not a quantity.

    NOVA and G-Engine spell a pack as base plus bonus — "1980 + 260 Genesis
    Crystals" — where we and G2B both spell the total, "2240 Genesis
    Crystals". Verified against production: our six Genshin SKUs sell through
    G2B as 60/330/1090/2240/3880/8080, and NOVA's six titles sum to exactly
    those. So the sum is the join key, not the leading number.

    The unit name carries whatever follows the digits, which is what keeps
    "150 + 15 Diamonds (First Top-Up Bonus)" — a one-off promotion that also
    totals 165 — out of the plain "165 Diamonds" bucket: its unit reads
    "diamonds first top up bonus" and matches nothing of ours.
    """
    # Not ``norm`` — that strips "+" along with every other punctuation mark,
    # which silently turned "1980 + 260 Genesis Crystals" into base 1980 and
    # unit "260 genesis crystals", matching nothing and looking like an
    # honest miss. Keep the plus, drop the rest.
    m = _AMOUNT.match(re.sub(r"[^a-z0-9+]+", " ", text.lower()).strip())
    if m is None:
        return None
    base, bonus, unit = m.group(1), m.group(2), m.group(3)
    return int(base) + (int(bonus) if bonus else 0), unit


async def main() -> None:
    factory = get_session_factory()

    # --- 1. Refresh the denomination cache for every game we are about to read.
    async with factory() as db:
        for brand, per_supplier in PAIRS.items():
            for supplier, game_id in per_supplier.items():
                count, error = await run_game_denomination_sync(
                    db, supplier_slug=supplier, game_id=game_id
                )
                await db.commit()
                flag = f" ERROR {error}" if error else ""
                print(f"sync {supplier:<8} {brand:<24} {game_id:<24} -> {count:>3} denoms{flag}")

    print()

    # --- 2. Match, and collect a plan.
    planned: list[tuple[str, str, str, str, str, str]] = []
    suspect: list[str] = []
    unmatched: list[tuple[str, str, str]] = []
    ambiguous: list[tuple[str, str, str, str]] = []
    refused: list[tuple[str, str, str]] = []

    async with factory() as db:
        for brand, per_supplier in PAIRS.items():
            skus = (
                await db.execute(
                    select(Sku)
                    .join(Product, Product.id == Sku.product_id)
                    .join(Brand, Brand.id == Product.brand_id)
                    .where(Brand.slug == brand)
                )
            ).scalars().all()

            for supplier, game_id in per_supplier.items():
                denoms = (
                    await db.execute(
                        select(SupplierCatalogCache).where(
                            SupplierCatalogCache.supplier_slug == supplier,
                            SupplierCatalogCache.kind == "game_denom",
                            SupplierCatalogCache.parent_external_id == game_id,
                        )
                    )
                ).scalars().all()
                by_title: dict[str, SupplierCatalogCache] = {}
                by_amount: dict[tuple[int, str], list[SupplierCatalogCache]] = {}
                for d in denoms:
                    by_title.setdefault(norm(d.title), d)
                    key = amount_key(d.title)
                    if key is not None:
                        by_amount.setdefault(key, []).append(d)

                for sku in skus:
                    existing = (
                        await db.execute(
                            select(SkuSupplierMapping).where(
                                SkuSupplierMapping.sku_id == sku.id,
                                SkuSupplierMapping.supplier_slug == supplier,
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        continue  # never overwrite a mapping somebody already set

                    if supplier not in RESERVE_SUPPLIERS:
                        # The one shape that could move live traffic: a SKU with
                        # no active non-reserve mapping has no incumbent, so the
                        # row written here would become the winner rather than
                        # lose the `created_at` tie-break. Refuse it and say so
                        # rather than trust the survey that said none exist.
                        incumbent = (
                            await db.execute(
                                select(SkuSupplierMapping).where(
                                    SkuSupplierMapping.sku_id == sku.id,
                                    SkuSupplierMapping.is_active.is_(True),
                                    SkuSupplierMapping.supplier_slug.notin_(
                                        tuple(RESERVE_SUPPLIERS)
                                    ),
                                )
                            )
                        ).scalars().first()
                        if incumbent is None:
                            refused.append((brand, supplier, sku.denomination or sku.sku_code))
                            continue
                    if not sku.denomination:
                        continue
                    hit = by_title.get(norm(sku.denomination))
                    if hit is None:
                        key = amount_key(sku.denomination)
                        candidates = by_amount.get(key, []) if key is not None else []
                        if len(candidates) > 1:
                            # Two upstream packs total the same amount. Picking
                            # one is a guess; a guess here sells the wrong pack.
                            names = ", ".join(c.title for c in candidates)
                            ambiguous.append((brand, supplier, sku.denomination, names))
                            continue
                        hit = candidates[0] if candidates else None
                    if hit is None:
                        unmatched.append((brand, supplier, sku.denomination))
                        continue
                    # Independent of the title arithmetic: a correct match should
                    # cost roughly what we already pay. An order-of-magnitude gap
                    # means the denominations are not the same thing, whatever
                    # the names sum to. Reported, not enforced — suppliers do
                    # differ on price, and that is the point of a second channel.
                    if sku.cost_usdt and hit.price_usdt:
                        ratio = float(hit.price_usdt) / float(sku.cost_usdt)
                        if not 0.5 <= ratio <= 2.0:
                            suspect.append(
                                f"  ~  {supplier:<8} {brand:<24} {sku.denomination:<30} "
                                f"ours {float(sku.cost_usdt):.4f} vs theirs "
                                f"{float(hit.price_usdt):.4f}  (x{ratio:.2f})"
                            )
                    planned.append(
                        (brand, supplier, sku.id, sku.denomination, game_id, hit.external_id)
                    )

    for brand, supplier, _sku_id, denom, game_id, variant in planned:
        print(f"map  {supplier:<8} {brand:<24} {denom:<34} -> {game_id}:{variant}")

    print()
    by_supplier: dict[str, int] = {}
    for _b, supplier, *_rest in planned:
        by_supplier[supplier] = by_supplier.get(supplier, 0) + 1
    print(f"planned: {len(planned)} new mappings {by_supplier}")
    print(f"price outliers among the planned rows: {len(suspect)}")
    for line in suspect:
        print(line)
    print(f"refused (would become the routing winner, no incumbent): {len(refused)}")
    for brand, supplier, denom in refused:
        print(f"  !  {supplier:<8} {brand:<24} {denom}")
    print(f"ambiguous (several upstream packs total the same): {len(ambiguous)}")
    for brand, supplier, denom, names in ambiguous:
        print(f"  ?  {supplier:<8} {brand:<24} {denom:<30} <- {names}")
    print(f"unmatched (nothing upstream with that total): {len(unmatched)}")
    for brand, supplier, denom in unmatched:
        print(f"  -  {supplier:<8} {brand:<24} {denom}")

    if not APPLY:
        print(f"\ndry run — nothing written. Re-run with APPLY=1.")
        return

    # --- 3. Write.
    async with factory() as db:
        for _brand, supplier, sku_id, _denom, game_id, variant in planned:
            await upsert_mapping(
                db,
                MappingUpsert(
                    sku_id=sku_id,
                    supplier_slug=supplier,
                    kind="game",
                    external_product_id=game_id,
                    external_variant_id=variant,
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by="backfill-2026-09-19",
                ),
            )
        await db.commit()
    print(f"\nwrote {len(planned)} mappings.")


if __name__ == "__main__":
    asyncio.run(main())
