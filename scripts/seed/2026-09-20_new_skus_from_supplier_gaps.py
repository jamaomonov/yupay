"""Nine SKUs our suppliers sell and we did not list.

Picked out of ``scripts/check_catalog_gaps.py`` and then read one by one,
because most of what that report lists should *not* be sold:

* **first-recharge packs** (Magic Chess RU, eight of them) are one-time per
  account — a customer who has already used theirs gets nothing;
* **"$0.49 Deal" … "$9.99 Deal", Lucky Bag, Ultra Skin Lucky Chest** (Blood
  Strike, twelve) are bundles whose contents rotate upstream, so we could not
  honestly describe what we were selling;
* **BP Coins** (Oxide, three) are a second currency and need their own product
  and form field, not a row here.

What is left is nine plain packs. Margins are the owner's, 2026-09-20: **15 %**
retail (``margin_percent``) and **6 %** wholesale (``b2b_markup_pct`` — already
what every neighbouring SKU carries).

``price_usd`` is not written by hand: it comes from
``catalog.admin_service._price_from_margin``, the same function the hourly
price refresh re-derives with, so the first cost move does not silently
rewrite a price that disagreed with the formula.

**Five of the nine have no non-reserve supplier**, because only NOVA sells
them. Auto routing never picks a reserve (ADR-0081), so each gets an explicit
``force_supplier: nova`` rule — the same shape the Free Fire lines carry. The
other four reach G-Engine on their own.

Dry run by default:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-09-20_new_skus_from_supplier_gaps.py

Then commit it:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-09-20_new_skus_from_supplier_gaps.py
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.core.ids import new_id
from yupay.modules.catalog.admin_service import _price_from_margin
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping
from yupay.modules.sourcing.service import set_rule

APPLY = os.environ.get("APPLY") == "1"

MARGIN_PCT = Decimal("15")
B2B_MARKUP_PCT = Decimal("6")

#: Products, read off production. Each brand's new rows join the product its
#: existing siblings already live in.
BONDS = "019f6b61-d313-7e52-bab1-e8afecc2306f"
PACKS = "01a055ce-5bea-73d2-b87a-2c94e0c33a2b"
MCGG_RU = "019fe85d-f4e4-7f40-a0d6-63974937a181"
FROST_STARS = "019fe85e-3ffb-7322-b486-e5d9592ff205"


@dataclass(frozen=True)
class NewSku:
    sku_code: str
    denomination: str
    product_id: str
    region: str
    cost_usdt: Decimal
    sort_order: int
    #: supplier -> (external_product_id, external_variant_id)
    mappings: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def price_usd(self) -> Decimal:
        return _price_from_margin(self.cost_usdt, MARGIN_PCT)

    @property
    def needs_nova_rule(self) -> bool:
        """No non-reserve supplier sells it, so auto routing would find none."""
        return not any(slug != "nova" for slug in self.mappings)


SPECS: tuple[NewSku, ...] = (
    # --- Whiteout Survival: the three tiers above our 7499 ---------------
    NewSku(
        "wos-9999",
        "9999 Frost Stars",
        FROST_STARS,
        "GLOBAL",
        Decimal("108.169980"),
        7,
        {"nova": ("whiteout_survival", "9999_frost_stars")},
    ),
    NewSku(
        "wos-18495",
        "18495 Frost Stars",
        FROST_STARS,
        "GLOBAL",
        Decimal("200.110740"),
        8,
        {"nova": ("whiteout_survival", "18495_frost_stars")},
    ),
    NewSku(
        "wos-29999",
        "29999 Frost Stars",
        FROST_STARS,
        "GLOBAL",
        Decimal("315.584940"),
        9,
        {"nova": ("whiteout_survival", "29999_frost_stars")},
    ),
    # --- Arena Breakout ---------------------------------------------------
    NewSku(
        "arena_breakout-8000",
        "8000 Bonds",
        BONDS,
        "GLOBAL",
        Decimal("154.458600"),
        8,
        {"gengine": ("13", "691")},
    ),
    NewSku(
        "arena_breakout-bulletproof-case-privileges",
        "Bulletproof Case Privileges",
        PACKS,
        "GLOBAL",
        Decimal("2.274600"),
        3,
        {
            "gengine": ("13", "70"),
            "nova": ("arena_breakout", "bulletproof_case_privileges"),
        },
    ),
    NewSku(
        "arena_breakout-composite-case-privileges",
        "Composite Case Privileges",
        PACKS,
        "GLOBAL",
        Decimal("6.844200"),
        4,
        {
            "gengine": ("13", "71"),
            "nova": ("arena_breakout", "composite_case_privileges"),
        },
    ),
    # --- Magic Chess Go Go (RU) ------------------------------------------
    NewSku(
        "mcgg_ru-weekly-card",
        "Weekly Card",
        MCGG_RU,
        "ru",
        Decimal("0.958800"),
        10,
        {"gengine": ("66", "637"), "nova": ("magic_chess_gogo_ru", "weekly_card")},
    ),
    NewSku(
        "mcgg_ru-battle-for-discounts",
        "Battle for Discounts",
        MCGG_RU,
        "ru",
        Decimal("0.978180"),
        11,
        {"nova": ("magic_chess_gogo_ru", "battle_for_discounts")},
    ),
    NewSku(
        "mcgg_ru-lukas-battle-bounty",
        "Lukas's Battle Bounty",
        MCGG_RU,
        "ru",
        Decimal("0.978180"),
        12,
        {"nova": ("magic_chess_gogo_ru", "lukas_s_battle_bounty")},
    ),
)


async def main() -> None:
    factory = get_session_factory()
    async with factory() as db:
        existing = set(
            (
                await db.execute(
                    select(Sku.sku_code).where(Sku.sku_code.in_([s.sku_code for s in SPECS]))
                )
            )
            .scalars()
            .all()
        )

        planned = [s for s in SPECS if s.sku_code not in existing]
        for s in SPECS:
            mark = "skip (exists)" if s.sku_code in existing else "create"
            route = "force nova" if s.needs_nova_rule else "auto"
            print(
                f"{mark:<14} {s.sku_code:<44} {s.denomination:<30} "
                f"cost ${s.cost_usdt:>10} -> ${s.price_usd:<8} {route}"
            )

        print(f"\n{len(planned)} to create, {len(existing)} already there.")
        if not APPLY:
            print("dry run — nothing written. Re-run with APPLY=1.")
            return

        for spec in planned:
            sku = Sku(
                id=new_id(),
                product_id=spec.product_id,
                sku_code=spec.sku_code,
                denomination=spec.denomination,
                region=spec.region,
                price_usd=spec.price_usd,
                cost_usdt=spec.cost_usdt,
                margin_percent=MARGIN_PCT,
                b2b_markup_pct=B2B_MARKUP_PCT,
                sort_order=spec.sort_order,
                active=True,
                visible_b2b=True,
            )
            db.add(sku)
            await db.flush()

            for supplier, (product, variant) in spec.mappings.items():
                await upsert_mapping(
                    db,
                    MappingUpsert(
                        sku_id=sku.id,
                        supplier_slug=supplier,
                        kind="game",
                        external_product_id=product,
                        external_variant_id=variant,
                        quantity=1,
                        extra={},
                        is_active=True,
                        updated_by="new-skus-2026-09-20",
                    ),
                )

            if spec.needs_nova_rule:
                # Only NOVA sells it, and a reserve is never auto-picked
                # (ADR-0081) — without this the SKU would take every order
                # and find no route.
                await set_rule(
                    db,
                    sku_id=sku.id,
                    mode="force_supplier",
                    supplier_slug="nova",
                    admin_id="new-skus-2026-09-20",
                )
            print(f"created {spec.sku_code} ({sku.id})")

        await db.commit()
        print(f"\nwrote {len(planned)} SKUs.")


if __name__ == "__main__":
    asyncio.run(main())
