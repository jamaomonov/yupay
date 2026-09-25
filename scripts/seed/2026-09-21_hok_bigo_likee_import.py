"""Import Honor of Kings, Bigo Live and Likee — all three carried by all three suppliers.

Run inside the api container:

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-09-21_hok_bigo_likee_import.py

Then the copy, which UPDATEs rows this creates:

    docker exec -i yupay-prod-postgres-1 sh -lc \
      'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
      < scripts/seed/hok_bigo_likee_seo.sql

## What the suppliers actually have (read live, 2026-09-21)

Unusually, **every rung below exists at all three suppliers**, which is the
opposite of the IMO import a day earlier where the ladders did not overlap at
all. So each SKU gets up to three mappings and a real failover — the first
brands in the catalogue where a supplier outage is survivable without an
operator.

Cost per rung, cheapest first: **G2B on every single one**, by a hair on Honor
of Kings and Bigo (~0.5%) and by ~9% on Likee, where G-Engine is the outlier.
G2B is also the non-reserve supplier, so `sourcing._pick_auto_mapping_slug`
picks it on its own — the mapping order below is written G2B-first anyway so
the *oldest* mapping, which is the tie-break, is the cheapest one.

NOVA mappings are created knowing they will not be auto-picked
(`RESERVE_SUPPLIERS`, ADR-0081). They are there so the sourcing screen can
compare prices and an operator can switch a SKU deliberately — the same
reason the NOVA backfill created them for PUBG and Free Fire.

## What is deliberately NOT imported

* **G2B's Honor of Kings promo packs** — `Standard Purchase Rebate Pack`,
  `Premium Purchase Rebate Pack`, `Double Token Lucky Bag`, `Honor Point Value
  Pack`. They are rotating first-purchase style bundles whose value depends on
  account state, they read as noise on a shelf next to plain token tiers, and
  the customer cannot tell from the name what they get. The two **passes**
  (`Weekly Card`, `Weekly Card Plus`) ARE imported: those are a recognisable
  product a player shops for by name.
* **Most of Bigo's 24 rungs and Likee's 14.** A storefront is not a price
  matrix — the same judgement `2026-08-31_g2b_gap_import` made for MLBB's 92
  rows. Bigo keeps ten tiers a customer actually chooses between and Likee
  nine; the dropped ones are listed in `_DROPPED` below so adding one back is
  a one-line change rather than a re-investigation.
* **Player validation.** G2B's `games_fields` answers `fields: ["userid"]` for
  all three and nothing about a validator; NOVA publishes one text field and no
  validator. Neither was tested against a real id, and a probe with an invented
  one proves nothing (ADR-0085). No `check` is wired — an unverified field
  beats a verification that verifies nothing.

Margin 15%, where the catalogue sits. Costs are the 2026-09-21 quotes; the
hourly refresh owns them from then on.

Idempotent: existing `sku_code`s are skipped, mappings converge, the re-sort
rewrites the ladder it already has.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select, update
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

MARGIN_PERCENT = Decimal("15")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"
#: `top-ups`, not `games`: the catalogue went to two categories on
#: 2026-09-21 (`2026-09-21_two_catalog_categories.sql`), one per
#: `products.kind`. All three brands here are `top_up`. This seed had not
#: been applied when the rename landed, so it is corrected rather than
#: superseded — applied as it stood it would have died on a category that
#: no longer exists.
CATEGORY_SLUG = "top-ups"

#: Rungs the suppliers sell that we choose not to shelve. Kept as a record so
#: "why is there no 700-diamond tier" has an answer that is not "nobody looked".
_DROPPED = {
    "bigo-live": [
        5,
        20,
        40,
        150,
        250,
        300,
        400,
        600,
        700,
        750,
        800,
        900,
        3000,
        4000,
        6000,
        7000,
        8000,
        9000,
    ],
    "likee": [1500, 2500, 3500, 4000, 4500],
}

# --- the form field -------------------------------------------------------
#
# One key, `player_id`, for all three: G2B's `games_fields` answers
# `fields: ["userid"]` — a single numeric id, no server, no region — and the
# G2B fulfiller reads `player_id` out of `fulfillment_data`. NOVA calls it
# `player_id` / `bigo_id` / `likee_id` on its own side and the adapter maps it.


_UNDER_NAME = {"ru": "под вашим именем", "en": "under your name", "uz": "ismingiz ostida"}


def _help(app: str, where: dict[str, str]) -> dict[str, str]:
    """Where-to-find-your-ID help, in three languages.

    ``where`` is per locale. It used to be one Russian string dropped into all
    three texts, so the English and Uzbek help for all three brands read
    "the ID is shown под вашим именем" — fixed on prod by
    ``2026-09-25_bigo_player_check.sql``.
    """
    return {
        "ru": (
            f"Откройте {app} и перейдите в профиль — ID показан {where['ru']}.\n"
            "Скопируйте номер, не набирайте вручную: ID состоит только из цифр, "
            "а одна ошибка отправит покупку другому человеку.\n"
            "Пароль не нужен — пополнение идёт по публичному ID."
        ),
        "en": (
            f"Open {app} and go to your profile — the ID is shown {where['en']}.\n"
            "Copy the number instead of retyping it: the ID is digits only, and one "
            "wrong digit sends the purchase to somebody else.\n"
            "No password needed — the top-up goes by public ID."
        ),
        "uz": (
            f"{app} ni oching va profilingizga oʻting — ID {where['uz']} koʻrsatilgan.\n"
            "Raqamni qoʻlda termay, nusxa oling: ID faqat raqamlardan iborat va bitta "
            "xato xaridni boshqa odamga yuboradi.\n"
            "Parol kerak emas — toʻldirish ommaviy ID orqali."
        ),
    }


def _fields(
    label: str, help_text: dict[str, str], check: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "check": check,
            "label": {"ru": label, "en": label, "uz": label},
            "required": True,
            "pattern": "^[0-9]{5,20}$",
            "placeholder": {"ru": "123456789", "en": "123456789", "uz": "123456789"},
            "help_text": help_text,
        },
    ]


# --- catalogue ------------------------------------------------------------
#
# Per rung: (sku suffix, shelf name, G2B cost, G2B variant, NOVA offer,
# G-Engine denomination id). `None` means that supplier does not carry it.

HOK: list[tuple[str, str, str, str, str | None, str | None]] = [
    ("16", "16 Tokens", "0.163", "16", "16_tokens", "152"),
    ("80", "80 Tokens", "0.847", "80", "80_tokens", "153"),
    ("240", "240 Tokens", "2.56", "240", "240_tokens", "154"),
    ("400", "400 Tokens", "4.264", "400", "400_tokens", "155"),
    ("560", "560 Tokens", "5.977", "560", "560_tokens", "156"),
    # G-Engine spells these "base + bonus" (800 + 30 = 830); the totals match
    # G2B and NOVA rung for rung. See the supplier-naming note in
    # 2026-09-19_backfill_nova_gengine_mappings.
    ("830", "830 Tokens", "8.548", "830", "830_tokens", "157"),
    ("1245", "1245 Tokens", "12.821", "1245", "1245_tokens", "158"),
    ("2508", "2508 Tokens", "25.643", "2508", "2508_tokens", "159"),
    ("4180", "4180 Tokens", "42.748", "4180", "4180_tokens", "160"),
    ("8360", "8360 Tokens", "85.507", "8360", "8360_tokens", "161"),
    # Passes. G-Engine carries neither.
    ("weekly", "Weekly Card", "0.959", "Weekly Card", "weekly_card", None),
    ("weekly-plus", "Weekly Card Plus", "2.815", "Weekly Card Plus", "weekly_card_plus", None),
]

BIGO: list[tuple[str, str, str, str, str | None, str | None]] = [
    ("10", "10 Diamonds", "0.184", "10", "10_diamonds", "460"),
    ("25", "25 Diamonds", "0.459", "25", "25_diamonds", "454"),
    ("50", "50 Diamonds", "0.928", "50", "50_diamonds", "455"),
    ("100", "100 Diamonds", "1.867", "100", "100_diamonds", "463"),
    ("200", "200 Diamonds", "3.733", "200", "200_diamonds", "464"),
    ("500", "500 Diamonds", "9.323", "500", "500_diamonds", "465"),
    ("1000", "1000 Diamonds", "18.646", "1000", "1000_diamonds", "466"),
    ("2000", "2000 Diamonds", "37.301", "2000", "2000_diamonds", "467"),
    # G-Engine's BIGO service stops at 2000 — these two are G2B + NOVA only.
    ("5000", "5000 Diamonds", "93.248", "5000", "5000_diamonds", None),
    ("10000", "10000 Diamonds", "186.476", "10000", "10000_diamonds", None),
]

LIKEE: list[tuple[str, str, str, str, str | None, str | None]] = [
    ("100", "100 Diamonds", "1.856", "100", "100_diamonds", "522"),
    ("200", "200 Diamonds", "3.713", "200", "200_diamonds", "523"),
    ("500", "500 Diamonds", "9.282", "500", "500_diamonds", "524"),
    ("1000", "1000 Diamonds", "18.564", "1000", "1000_diamonds", "525"),
    ("2000", "2000 Diamonds", "37.118", "2000", "2000_diamonds", "527"),
    ("3000", "3000 Diamonds", "55.712", "3000", "3000_diamonds", "529"),
    ("5000", "5000 Diamonds", "92.8", "5000", "5000_diamonds", "533"),
    ("10000", "10000 Diamonds", "185.599", "10000", "10000_diamonds", "534"),
    ("20000", "20000 Diamonds", "371.188", "20000", "20000_diamonds", "535"),
]

BRANDS: list[dict[str, Any]] = [
    {
        "slug": "honor-of-kings",
        "name": "Honor of Kings",
        "product_slug": "hok-tokens",
        "product_name": "Токены",
        "sku_prefix": "hok",
        "g2b_game": "hok",
        "nova_category": "honor_of_kings",
        "gengine_service": "23",
        "fields": _fields(
            "Player ID",
            _help(
                "Honor of Kings",
                {
                    "ru": "в профиле рядом с именем",
                    "en": "next to your name",
                    "uz": "ismingiz yonida",
                },
            ),
        ),
        "rungs": HOK,
    },
    {
        "slug": "bigo-live",
        "name": "Bigo Live",
        "product_slug": "bigo-diamonds",
        "product_name": "Алмазы",
        "sku_prefix": "bigo",
        "g2b_game": "bigo",
        "nova_category": "bigo_live",
        "gengine_service": "49",
        "fields": _fields(
            "Bigo ID",
            _help("Bigo Live", _UNDER_NAME),
            # G2B's `bigo` validator is real — probed 2026-09-25, see ADR-0031.
            check={"provider": "g2b", "server_field": None},
        ),
        "rungs": BIGO,
    },
    {
        "slug": "likee",
        "name": "Likee",
        "product_slug": "likee-diamonds",
        "product_name": "Алмазы",
        "sku_prefix": "likee",
        "g2b_game": "likee",
        "nova_category": "likee",
        "gengine_service": "54",
        "fields": _fields("Likee ID", _help("Likee", _UNDER_NAME)),
        "rungs": LIKEE,
    },
]

_LOCALES = ("ru", "en", "uz")


def _price(cost: str) -> Decimal:
    return (Decimal(cost) * (Decimal(1) + MARGIN_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _category_id(session: Any) -> str:
    row = (
        await session.execute(select(Category).where(Category.slug == CATEGORY_SLUG))
    ).scalar_one()
    return str(row.id)


async def _brand(session: Any, spec: dict[str, Any], category_id: str) -> str:
    from yupay.modules.catalog import admin_schemas as cs
    from yupay.modules.catalog import admin_service as catalog

    row = (
        await session.execute(select(Brand).where(Brand.slug == spec["slug"]))
    ).scalar_one_or_none()
    if row is not None:
        return str(row.id)
    brand = await catalog.create_brand(
        session,
        cs.BrandCreate(
            slug=spec["slug"],
            category_id=category_id,
            translations=[cs.TranslationIn(locale=loc, name=spec["name"]) for loc in _LOCALES],
        ),
    )
    return str(brand.id)


async def _product(session: Any, spec: dict[str, Any], brand_id: str) -> str:
    from yupay.modules.catalog import admin_schemas as cs
    from yupay.modules.catalog import admin_service as catalog

    row = (
        await session.execute(
            select(Product).where(
                Product.brand_id == brand_id, Product.slug == spec["product_slug"]
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return str(row.id)
    product = await catalog.create_product(
        session,
        cs.ProductCreate(
            brand_id=brand_id,
            slug=spec["product_slug"],
            kind="top_up",
            required_fields=spec["fields"],
            translations=[
                cs.TranslationIn(locale=loc, name=spec["product_name"]) for loc in _LOCALES
            ],
        ),
    )
    return str(product.id)


async def _rungs(session: Any, spec: dict[str, Any], product_id: str) -> tuple[int, int]:
    from yupay.modules.catalog import admin_schemas as cs
    from yupay.modules.catalog import admin_service as catalog

    created = mapped = 0
    for position, (suffix, name, cost, g2b_v, nova_v, ge_v) in enumerate(spec["rungs"]):
        code = f"{spec['sku_prefix']}-{suffix}"
        row = (await session.execute(select(Sku).where(Sku.sku_code == code))).scalar_one_or_none()
        if row is None:
            sku = await catalog.create_sku(
                session,
                cs.SkuCreate(
                    product_id=product_id,
                    sku_code=code,
                    denomination=name,
                    price_usd=_price(cost),
                    cost_usdt=Decimal(cost),
                    sort_order=position,
                ),
            )
            sku_id, created = sku.id, created + 1
        else:
            sku_id = row.id

        # G2B first, deliberately: among non-reserve suppliers the OLDEST
        # active mapping wins the routing tie-break, and G2B is the cheapest
        # on every rung here.
        for slug, product_ref, variant in (
            ("g2b", spec["g2b_game"], g2b_v),
            ("gengine", spec["gengine_service"], ge_v),
            ("nova", spec["nova_category"], nova_v),
        ):
            if variant is None:
                continue
            await upsert_mapping(
                session,
                MappingUpsert(
                    sku_id=sku_id,
                    supplier_slug=slug,
                    kind="game",
                    external_product_id=product_ref,
                    external_variant_id=variant,
                    quantity=1,
                    extra={},
                    is_active=True,
                    updated_by=ADMIN_ID,
                ),
            )
            mapped += 1
    return created, mapped


async def _order_by_price(session: Any, product_id: str) -> None:
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


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        category_id = await _category_id(session)
        report = []
        for spec in BRANDS:
            brand_id = await _brand(session, spec, category_id)
            product_id = await _product(session, spec, brand_id)
            created, mapped = await _rungs(session, spec, product_id)
            await _order_by_price(session, product_id)
            report.append((spec["slug"], brand_id, len(spec["rungs"]), created, mapped))
        await session.commit()

    for slug, brand_id, rungs, created, mapped in report:
        print(f"{slug:<16} brand={brand_id}  rungs={rungs}  new_skus={created}  mappings={mapped}")
    print()
    print("NEXT: run scripts/seed/hok_bigo_likee_seo.sql, then upload the three brand logos.")


asyncio.run(main())
