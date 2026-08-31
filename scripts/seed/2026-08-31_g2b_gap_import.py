"""Close the G2B assortment gaps for PUBG Mobile, Free Fire, MLBB and Arena
Breakout (+Infinite), and switch PUBG's big UC tiers to G2B's discounted
variants.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-31_g2b_gap_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-31_g2b_gap_import.py

What this is (analysis of 2026-08-31, live ``games_catalogue`` vs prod
mappings — every cost below is G2B's quote from that snapshot; the hourly
price-refresh job owns them from then on):

* **MLBB global** — G2B lists a dense grid of every rechargeable diamond sum
  (92 rows). A storefront is not a price matrix: we add the twelve tiers a
  customer actually shops between plus the two Elite packs, into the existing
  ``mlbb-diamonds`` product. The RU product gets its one missing pack. The
  global/RU region split (``mlbb`` vs ``mlbb_ru``) is deliberate and stays —
  see 2026-08-09_mobile_legends_import.py for the eligibility matrix.
* **PUBG WOW Coins** — a separate currency for the World of Wonder UGC mode
  (paid items on player-made maps), same numerals as UC but NOT UC. Sold as
  its own product so nobody buys it thinking it is UC.
* **PUBG packs** — First Purchase / Weekly Deal / Mythic Emblem / Firearm
  Materials are rotating promo packs; G2B can delist any of them without
  notice. Imported knowingly: the supplier-catalog watchdog deactivates a SKU
  whose variant disappears upstream and pings Telegram.
* **Arena Breakout** — starter pack + the two 30-day storage cases; the
  Infinite skin bundles are limited cosmetic sets, same watchdog caveat.
* **Discounted UC switch** — G2B added «1800/3850/8100 UC (discounted)»
  (~18% cheaper wholesale) next to the regular tiers. We repoint the three
  existing mappings at the discounted variants and RAISE ``margin_percent``
  so the shelf price stays exactly where it is: the whole discount lands in
  our margin (operator's decision, 2026-08-31). Setting the margin from
  price/cost keeps the hourly refresh from silently dropping the shelf price
  to cost×20%.

Idempotent: additions skip existing ``sku_code``s, the mapping switch and
margin write converge on the same values, re-ordering rewrites the ladder it
already has.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.schemas import (
    DenomImportIn,
    GameImportIn,
    ProductImportIn,
)
from yupay.modules.integrations.service import _import_denomination, import_game

MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- additions to existing products ---------------------------------------
# (product_slug, game_code, [(catalogue_name, shelf_label, cost_usdt, sku_code)])
# catalogue_name must match G2B byte for byte — it becomes external_variant_id.

ADD_TO_EXISTING: list[tuple[str, str, list[tuple[str, str, str, str]]]] = [
    (
        "mlbb-diamonds",
        "mlbb",
        [
            ("Weekly Elite Pack", "Weekly Elite Pack", "0.765", "mlbb-weekly-elite-pack"),
            ("172", "172 Diamonds", "2.336", "mlbb-172"),
            ("257", "257 Diamonds", "3.346", "mlbb-257"),
            ("Monthly Elite Pack", "Monthly Elite Pack", "3.774", "mlbb-monthly-elite-pack"),
            ("344", "344 Diamonds", "4.661", "mlbb-344"),
            ("514", "514 Diamonds", "6.701", "mlbb-514"),
            ("706", "706 Diamonds", "9.19", "mlbb-706"),
            ("963", "963 Diamonds", "12.536", "mlbb-963"),
            ("1498", "1498 Diamonds", "19.553", "mlbb-1498"),
            ("1928", "1928 Diamonds", "25.378", "mlbb-1928"),
            ("2539", "2539 Diamonds", "32.467", "mlbb-2539"),
            ("4394", "4394 Diamonds", "55.57", "mlbb-4394"),
            ("6944", "6944 Diamonds", "88.393", "mlbb-6944"),
            ("9994", "9994 Diamonds", "125.501", "mlbb-9994"),
        ],
    ),
    (
        "mlbb-diamonds-ru",
        "mlbb_ru",
        [
            (
                "Limited-Time Value Pack",
                "Limited-Time Value Pack",
                "0.275",
                "mlbb_ru-limited-time-value-pack",
            ),
        ],
    ),
    (
        "free-fire-membership",
        "freefire_cis",
        [
            ("Weekly Lite", "Weekly Lite", "0.38", "freefire_cis-weekly-lite"),
        ],
    ),
]

# --- new products under existing brands -----------------------------------
# Brand and required_fields are copied from a sibling product: the customer
# fills in the same account fields whether they buy UC, WOW Coins or a pack.
# (sibling_product_slug, new_slug, ru_name, game_code, denoms)

NEW_PRODUCTS: list[tuple[str, str, str, str, list[tuple[str, str, str, str]]]] = [
    (
        "pubg-uc",
        "pubg-wow-coins",
        "WOW Coins (World of Wonder)",
        "pubgm",
        [
            ("60 WOW Coins", "60 WOW Coins", "0.908", "pubgm-wow-60"),
            ("325 WOW Coins", "325 WOW Coins", "4.59", "pubgm-wow-325"),
            ("660 WOW Coins", "660 WOW Coins", "9.19", "pubgm-wow-660"),
            ("1800 WOW Coins", "1800 WOW Coins", "22.97", "pubgm-wow-1800"),
            ("3850 WOW Coins", "3850 WOW Coins", "45.92", "pubgm-wow-3850"),
            ("8100 WOW Coins", "8100 WOW Coins", "91.851", "pubgm-wow-8100"),
        ],
    ),
    (
        "pubg-uc",
        "pubg-packs",
        "Наборы и паки",
        "pubgm",
        [
            ("First Purchase Pack", "First Purchase Pack", "0.88", "pubgm-first-purchase-pack"),
            ("Weekly Deal Pack 1", "Weekly Deal Pack 1", "0.882", "pubgm-weekly-deal-pack-1"),
            (
                "Upgradable Firearm Materials Pack",
                "Upgradable Firearm Materials Pack",
                "2.636",
                "pubgm-firearm-materials-pack",
            ),
            (
                "Weekly Mythic Emblem Value Pack",
                "Weekly Mythic Emblem Value Pack",
                "2.646",
                "pubgm-weekly-mythic-emblem-value-pack",
            ),
            ("Weekly Deal Pack 2", "Weekly Deal Pack 2", "2.646", "pubgm-weekly-deal-pack-2"),
            ("Mythic Emblem Pack", "Mythic Emblem Pack", "4.389", "pubgm-mythic-emblem-pack"),
        ],
    ),
    (
        "arena-breakout-bonds",
        "arena-breakout-packs",
        "Наборы и кейсы",
        "arena_breakout",
        [
            ("Beginner Select", "Beginner Select", "0.714", "arena_breakout-beginner-select"),
            (
                "Bulletproof Case (30d)",
                "Bulletproof Case (30 days)",
                "2.152",
                "arena_breakout-bulletproof-case-30d",
            ),
            (
                "Composition Case (30d)",
                "Composition Case (30 days)",
                "6.477",
                "arena_breakout-composition-case-30d",
            ),
        ],
    ),
    (
        "arena-breakout-infinite-coins",
        "arena-breakout-infinite-bundles",
        "Скин-бандлы",
        "arena_breakout_infinite",
        [
            (
                "Copper Works Skin Bundle I",
                "Copper Works Skin Bundle I",
                "4.947",
                "arena_breakout_infinite-copper-works-skin-bundle-1",
            ),
            (
                "Copper Works Skin Bundle II",
                "Copper Works Skin Bundle II",
                "4.947",
                "arena_breakout_infinite-copper-works-skin-bundle-2",
            ),
            (
                "Classic Craftsmanship Skin Bundle I",
                "Classic Craftsmanship Skin Bundle I",
                "4.947",
                "arena_breakout_infinite-classic-craftsmanship-skin-bundle-1",
            ),
            (
                "Classic Craftsmanship Skin Bundle II",
                "Classic Craftsmanship Skin Bundle II",
                "4.947",
                "arena_breakout_infinite-classic-craftsmanship-skin-bundle-2",
            ),
        ],
    ),
]

# --- discounted-UC mapping switch -----------------------------------------
# (sku_code, discounted_catalogue_name, discounted_cost_usdt)

SWITCH_DISCOUNT: list[tuple[str, str, str]] = [
    ("pubgm-1800", "1800 UC (discounted)", "22.13"),
    ("pubgm-3850", "3850 UC (discounted)", "43.25"),
    ("pubgm-8100", "8100 UC (discounted)", "85.5"),
]


async def _product(session: Any, slug: str) -> Product:
    return (await session.execute(select(Product).where(Product.slug == slug))).scalar_one()


async def _existing_codes(session: Any, codes: list[str]) -> set[str]:
    return set(
        (await session.execute(select(Sku.sku_code).where(Sku.sku_code.in_(codes))))
        .scalars()
        .all()
    )


async def _sibling_region(session: Any, product_id: str) -> str:
    row = (
        await session.execute(
            select(Sku.region).where(Sku.product_id == product_id).order_by(Sku.sort_order)
        )
    ).scalars().first()
    return row or "GLOBAL"


async def _order_skus_by_price(session: Any, product_id: str) -> int:
    skus = (
        (
            await session.execute(
                select(Sku).where(Sku.product_id == product_id).order_by(Sku.price_usd)
            )
        )
        .scalars()
        .all()
    )
    for i, sku in enumerate(skus):
        await session.execute(update(Sku).where(Sku.id == sku.id).values(sort_order=i))
    return len(skus)


def _denoms(rows: list[tuple[str, str, str, str]], region: str) -> list[DenomImportIn]:
    return [
        DenomImportIn(
            catalogue_name=name,
            denomination=label,
            sku_code=code,
            cost_usdt=Decimal(cost),
            region=region,
        )
        for name, label, cost, code in rows
    ]


async def _ensure_margin(session: Any, codes: list[str]) -> None:
    """Backfill margin_percent=20 where the import path left it NULL.

    The hourly cost refresh only moves ``price_usd`` for SKUs with a saved
    margin; without this, a supplier price change would update the cost and
    silently freeze the shelf price.
    """
    await session.execute(
        update(Sku)
        .where(Sku.sku_code.in_(codes), Sku.margin_percent.is_(None))
        .values(margin_percent=MARGIN_PERCENT)
    )


async def main() -> None:
    async with get_session_factory()() as session:
        # -- 1. additions to existing products
        for slug, game_code, rows in ADD_TO_EXISTING:
            product = await _product(session, slug)
            region = await _sibling_region(session, str(product.id))
            existing = await _existing_codes(session, [r[3] for r in rows])
            created = 0
            for position, denom in enumerate(_denoms(rows, region)):
                if denom.sku_code in existing:
                    continue
                await _import_denomination(
                    session,
                    product_id=str(product.id),
                    game_code=game_code,
                    denom=denom,
                    margin_percent=MARGIN_PERCENT,
                    admin_id=ADMIN_ID,
                    sort_order=100 + position,  # ladder is rewritten below anyway
                )
                created += 1
            await _ensure_margin(session, [r[3] for r in rows])
            ordered = await _order_skus_by_price(session, str(product.id))
            print(f"{slug}: +{created} skus (skipped {len(existing)}), ladder={ordered}")

        # -- 2. new products under existing brands
        for sibling_slug, new_slug, ru_name, game_code, rows in NEW_PRODUCTS:
            existing_product = (
                await session.execute(select(Product).where(Product.slug == new_slug))
            ).scalar_one_or_none()
            if existing_product is not None:
                print(f"{new_slug}: already exists — skipping import")
                await _order_skus_by_price(session, str(existing_product.id))
                continue
            sibling = await _product(session, sibling_slug)
            region = await _sibling_region(session, str(sibling.id))
            payload = GameImportIn(
                game_code=game_code,
                target="existing_brand",
                brand_id=str(sibling.brand_id),
                new_brand=None,
                product=ProductImportIn(
                    slug=new_slug,
                    name=ru_name,
                    required_fields=sibling.required_fields,
                ),
                margin_percent=MARGIN_PERCENT,
                denominations=_denoms(rows, region),
            )
            result = await import_game(session, payload, admin_id=ADMIN_ID)
            await _ensure_margin(session, [r[3] for r in rows])
            ordered = await _order_skus_by_price(session, result.product_id)
            print(
                f"{new_slug}: product={result.product_id} skus={result.created_skus} "
                f"mappings={result.created_mappings} skipped={result.skipped} ladder={ordered}"
            )

        # -- 3. discounted-UC switch: repoint mapping, take the discount as margin
        for sku_code, variant, cost in SWITCH_DISCOUNT:
            sku = (
                await session.execute(select(Sku).where(Sku.sku_code == sku_code))
            ).scalar_one()
            new_cost = Decimal(cost)
            # margin chosen so price_usd stays exactly where it is; quantized to
            # the column's 4dp so the hourly refresh recomputes the same price.
            new_margin = ((sku.price_usd / new_cost - 1) * 100).quantize(Decimal("0.0001"))
            await session.execute(
                update(SkuSupplierMapping)
                .where(
                    SkuSupplierMapping.sku_id == sku.id,
                    SkuSupplierMapping.supplier_slug == "g2b",
                )
                .values(external_variant_id=variant, updated_by=ADMIN_ID)
            )
            await session.execute(
                update(Sku)
                .where(Sku.id == sku.id)
                .values(cost_usdt=new_cost, margin_percent=new_margin)
            )
            print(
                f"{sku_code}: mapping → {variant!r}, cost {sku.cost_usdt} → {new_cost}, "
                f"margin → {new_margin}% (shelf price kept at {sku.price_usd})"
            )

        await session.commit()
        print("committed")


asyncio.run(main())
