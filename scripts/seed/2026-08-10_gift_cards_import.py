"""Onboard the Gift cards category with Discord and Roblox vouchers from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-10_gift_cards_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-10_gift_cards_import.py

Two firsts for this catalog, which is why this is a script of its own rather
than a call to ``integrations.service.import_game``:

* **A second category.** Until now the storefront has shipped exactly one,
  ``games``. Everything downstream — category nav, `/store?cat=`, the miniapp's
  tab strip — has therefore only ever been exercised with a single tab.
* **Vouchers.** ``import_game`` hardcodes ``kind="top_up"`` products and
  ``kind="game"`` mappings; a gift card is ``kind="voucher"`` on both. The
  fulfilment side of vouchers was built long ago (purchase → poll → a
  ``voucher_code`` artifact) and has simply never had a product to run on.

**Stock is read at import time, not left to the first scheduler tick.** Each G2B
product id is fetched before the SKU is written, which does two jobs: it seeds
``supplier_stock`` so the storefront is correct from the first render, and it
proves the id actually resolves. A typo would otherwise become a mapping that
looks fine until a customer pays for it. An id that 404s aborts the import.

Voucher products carry **no** ``required_fields``. There is no account to credit
— the customer receives a code, and the email the order already collects is
where it goes. That absence is the whole difference in the checkout UI.

Idempotent: category, brands and products are reused when present, and existing
``sku_code``s are skipped. Re-running refreshes nothing except newly added lines
— use the scheduler job for stock.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cat_schemas
from yupay.modules.catalog import admin_service as catalog
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.integrations.stock_refresh import normalise_stock

CATEGORY_SLUG = "gift-cards"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

CATEGORY_NAMES = {
    "ru": "Подарочные карты",
    "en": "Gift cards",
    "uz": "Sovgʻa kartalari",
}

# --- what we sell ----------------------------------------------------------
#
# `g2b_id` is the product id in G2B's voucher catalogue (`GET /products/{id}`),
# which is also what the mapping sends at purchase time. Costs are not written
# here: they are read live during the import, together with stock, so a price
# that moved upstream cannot be baked in stale.
#
# Roblox: G2B's "Roblox Global" category also lists 100 and 200 Robux, left out
# deliberately — at $2.68 for 100 they cost more than twice per Robux what the
# 800 pack does, and a shelf that quietly punishes the smallest purchase is
# worse than one that starts higher.
#
# Discord: the three Nitro tiers G2B carries. These are POSA vouchers redeemed
# at posa.mintroute.com rather than inside Discord — see the SEO seed, where
# that surprise is the first thing the page explains.

BRANDS: list[dict[str, Any]] = [
    {
        "slug": "roblox",
        "name": "Roblox",
        "products": [
            {
                "slug": "roblox-robux-global",
                "name": "Robux (Global)",
                "skus": [
                    ("roblox-800", "800 Robux", 107),
                    ("roblox-1000", "1000 Robux", 1154),
                    ("roblox-2000", "2000 Robux", 108),
                    ("roblox-4500", "4500 Robux", 109),
                    ("roblox-10000", "10000 Robux", 110),
                ],
            }
        ],
    },
    {
        "slug": "discord",
        "name": "Discord",
        "products": [
            {
                "slug": "discord-nitro",
                "name": "Nitro",
                "skus": [
                    ("discord-nitro-basic-1m", "Nitro Basic — 1 месяц", 92),
                    ("discord-nitro-1m", "Nitro — 1 месяц", 93),
                    ("discord-nitro-1y", "Nitro — 1 год", 94),
                ],
            }
        ],
    },
]


def _sell_price(cost: Decimal) -> Decimal:
    """cost × (1 + margin), rounded to cents the same way import_game does."""
    return (cost * (Decimal(1) + MARGIN_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _ensure_category(session: Any) -> str:
    existing = (
        await session.execute(select(Category).where(Category.slug == CATEGORY_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"category {CATEGORY_SLUG}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_category(
        session,
        cat_schemas.CategoryCreate(
            slug=CATEGORY_SLUG,
            # lucide name, matching how `games` carries "gamepad-2".
            icon="gift",
            # After games: top-ups are the business, cards are the sideline.
            sort_order=1,
            translations=[
                cat_schemas.CategoryTranslationIn(locale=loc, name=name)
                for loc, name in CATEGORY_NAMES.items()
            ],
        ),
    )
    print(f"category {CATEGORY_SLUG}: created {row.id}")
    return str(row.id)


async def _ensure_brand(session: Any, *, slug: str, name: str, category_id: str) -> str:
    existing = (await session.execute(select(Brand).where(Brand.slug == slug))).scalar_one_or_none()
    if existing is not None:
        print(f"  brand {slug}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_brand(
        session,
        cat_schemas.BrandCreate(
            slug=slug,
            category_id=category_id,
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name) for loc in ("ru", "en", "uz")
            ],
        ),
    )
    print(f"  brand {slug}: created {row.id}")
    return str(row.id)


async def _ensure_product(session: Any, *, slug: str, name: str, brand_id: str) -> tuple[str, bool]:
    existing = (
        await session.execute(select(Product).where(Product.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"    product {slug}: reusing {existing.id}")
        return str(existing.id), False
    row = await catalog.create_product(
        session,
        cat_schemas.ProductCreate(
            slug=slug,
            brand_id=brand_id,
            kind="voucher",
            supplier_hint="g2b",
            # No fields: a voucher has no account to credit. The code goes to
            # the email the order already carries.
            required_fields=[],
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name) for loc in ("ru", "en", "uz")
            ],
        ),
    )
    print(f"    product {slug}: created {row.id}")
    return str(row.id), True


async def main() -> None:
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller):
        raise SystemExit("g2b adapter is not registered — is G2B_API_KEY set?")
    client = fulfiller.client_for_reads()

    async with get_session_factory()() as session:
        category_id = await _ensure_category(session)

        for brand_spec in BRANDS:
            brand_id = await _ensure_brand(
                session,
                slug=str(brand_spec["slug"]),
                name=str(brand_spec["name"]),
                category_id=category_id,
            )
            for product_spec in brand_spec["products"]:
                product_id, _created = await _ensure_product(
                    session,
                    slug=str(product_spec["slug"]),
                    name=str(product_spec["name"]),
                    brand_id=brand_id,
                )
                existing_codes = set(
                    (
                        await session.execute(
                            select(Sku.sku_code).where(
                                Sku.sku_code.in_([c for c, _, _ in product_spec["skus"]])
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                for position, (sku_code, denomination, g2b_id) in enumerate(product_spec["skus"]):
                    if sku_code in existing_codes:
                        print(f"      {sku_code}: exists — skipped")
                        continue

                    remote = await client.fetch_product(str(g2b_id))
                    if remote is None:
                        raise SystemExit(
                            f"G2B product {g2b_id} for {sku_code} does not resolve — "
                            "refusing to create a mapping that cannot be fulfilled"
                        )
                    cost = Decimal(str(remote["unit_price"]))
                    stock = normalise_stock(remote.get("stock"))

                    sku = await catalog.create_sku(
                        session,
                        cat_schemas.SkuCreate(
                            product_id=product_id,
                            sku_code=sku_code,
                            denomination=denomination,
                            price_usd=_sell_price(cost),
                            cost_usdt=cost,
                            sort_order=position,
                        ),
                    )
                    sku.supplier_stock = stock
                    await upsert_mapping(
                        session,
                        MappingUpsert(
                            sku_id=sku.id,
                            supplier_slug="g2b",
                            kind="voucher",
                            external_product_id=str(g2b_id),
                            # Games need a denomination id here; vouchers are
                            # identified by the product alone.
                            external_variant_id=None,
                            quantity=1,
                            extra={},
                            is_active=True,
                            updated_by=ADMIN_ID,
                        ),
                    )
                    print(
                        f"      {sku_code}: g2b={g2b_id} cost={cost} "
                        f"price={_sell_price(cost)} stock={stock}"
                    )

        await session.commit()
        print("committed")


asyncio.run(main())
