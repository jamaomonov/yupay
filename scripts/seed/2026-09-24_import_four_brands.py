"""Import four brands: Minecraft, Stumble Guys, Marvel Rivals, AFK Journey.

Run inside the api container. Preview first, then apply:

    docker exec -i -e APPLY=0 yupay-prod-api-1 python - < scripts/seed/2026-09-24_import_four_brands.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-09-24_import_four_brands.py

## Why these four

Our sales are concentrated: six brands carry 95% of orders and fourteen of the
twenty-five we already sell do fewer than ten a quarter. So this is not "add
more titles" — it is four picked against evidence.

- **Minecraft** is the top-grossing arcade title in Uzbekistan (Similarweb,
  2026-08) and the only candidate with no region problem at all: both products
  are Global.
- **Call of Duty Mobile, Roblox, Mobile Legends, Free Fire, PUBG Mobile and
  CS:GO** are what the market survey names as played here. We sell five of the
  six; CoD is held back pending a live test of whether a KZ-region top-up
  reaches an Uzbek account.
- **Stumble Guys** and **Marvel Rivals** are carried by all four suppliers and
  sit next to an audience that already converts for us (Roblox: 58 orders in
  90 days).
- **AFK Journey** is carried by all four suppliers.

## Routing: not to the cheapest

FazerCards is cheapest on every rung here — Stumble's 250 Gems is $0.72 against
G2B's $0.908, a 26% gap — and nothing routes there. `fzr` and `nova` are both
in ``RESERVE_SUPPLIERS``, so ``_pick_auto_mapping_slug`` skips them and the
alphabetical tie-break lands on `g2b` (or `gengine`, where G2B has no price).
That is deliberate: these are brands with no sales history, and FazerCards is
a trial account whose plan expires 2026-09-29. Every rung is mapped to it
anyway, so the brand comparison screen shows the saving and an operator can
switch with one `force_supplier` rule once the plan is settled — at which
point ADR-0091 re-prices the SKU and keeps the difference.

## What is deliberately left out

- **Minecraft Deluxe and Ultimate editions.** Only FazerCards and NOVA carry
  them, both reserves, so they would route nowhere without being pinned to a
  supplier whose access expires this week. The base edition and Minecoins are
  on G-Engine and route themselves.
- **Marvel Rivals "Pick-Up Bundle"** ($2.683, G2B only): we cannot tell what
  is in it, and a shelf listing we cannot describe is not one to sell.

## The customer-facing text needs a human pass

The three games each take a public account id, and the form's `key` is
``player_id`` for all of them — that is what both the G2B adapter
(``_IDENTIFIER_KEYS``) and the panel field builder (``panel_fields``) resolve,
whatever the vendor calls its own field. The **label** carries each game's own
wording.

The help text says where the id lives in general terms and why to copy rather
than retype. It does **not** give exact menu paths, because those were not
verified against the running games — writing confident steps that are wrong is
how a customer sends money to a stranger. Refine them (and add ``help_images``)
once someone has each game open.

## Two owner decisions, 2026-09-24

**Margin 12% on the games, 10% on Minecraft** — under the neighbours
(blood-strike 17.1%, whiteout-survival 15.5%, Roblox 13.9%). These are four
brands with no history, and a thin price is the cheapest way to learn whether
there is demand at all.

**Created switched off.** Two customer-facing things are not ready: the brands
have no logo or hero image, and the help text has not been checked against the
running games. Only the brand row is inactive, so going live is one toggle
each rather than twenty-six.

Idempotent: an existing slug is skipped, never re-priced. Mappings converge.
"""

from __future__ import annotations

import asyncio
import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cs
from yupay.modules.catalog import admin_service as cat
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
APPLY = os.environ.get("APPLY") == "1"
TOP_UPS = "019f6a61-5db6-76a1-901f-54e1a9ad3c48"
GIFT_CARDS = "019fe85e-92b3-7551-989e-6556a2f99ae8"

#: Owner's call 2026-09-24: go in under the neighbours — these are four
#: brands with no sales history, and a thin price is the cheapest way to find
#: out whether there is demand at all. For reference, blood-strike runs 17.1%,
#: whiteout-survival 15.5% and Roblox 13.9%.
MARGIN_GAME = Decimal("12")
MARGIN_VOUCHER = Decimal("10")

#: Created switched **off**. Everything below exists, is priced and is mapped,
#: but the storefront filters on ``brand.active`` so nothing shows until
#: somebody flips it. Two things are not ready at seed time and both are
#: customer-facing: the brands have no logo or hero image, and the "where to
#: find your ID" help text has not been checked against the running games.
#: Only the BRAND is switched off -- its products and SKUs stay active, so
#: going live is one toggle per brand rather than twenty-six.
BRAND_ACTIVE = False


def _id_field(
    label_ru: str, label_en: str, label_uz: str, where_ru: str, where_en: str, where_uz: str
) -> dict[str, Any]:
    """The one form field a top-up game needs: the buyer's public account id.

    ``key`` is always ``player_id``. Both the G2B adapter and the panel field
    builder resolve that to whatever the vendor calls its own field, so the
    label can carry the game's wording without the plumbing caring.
    """
    copy_ru = (
        "\nКопируйте номер кнопкой, а не вручную: одна неверная цифра отправит "
        "покупку чужому игроку.\nПароль не нужен — пополнение идёт по публичному ID."
    )
    copy_en = (
        "\nUse the copy button rather than retyping: one wrong digit sends the "
        "purchase to a stranger.\nNo password needed — top-up is by public ID."
    )
    copy_uz = (
        "\nRaqamni qoʻlda termay, nusxa olish tugmasidan foydalaning: bitta xato "
        "raqam xaridni begona oʻyinchiga yuboradi.\nParol kerak emas — toʻldirish "
        "ommaviy ID orqali."
    )
    return {
        "key": "player_id",
        "type": "text",
        "required": True,
        "label": {"ru": label_ru, "en": label_en, "uz": label_uz},
        "placeholder": {"ru": "123456789", "en": "123456789", "uz": "123456789"},
        "help_text": {
            "ru": where_ru + copy_ru,
            "en": where_en + copy_en,
            "uz": where_uz + copy_uz,
        },
        "pattern": r"^[A-Za-z0-9#-]{4,32}$",
    }


#: ``(slug, category_id, sort_order, {locale: (name, short, [highlights])})``
BRANDS: list[tuple[str, str, int, dict[str, tuple[str, str, list[str]]]]] = [
    (
        "minecraft",
        GIFT_CARDS,
        21,
        {
            "ru": (
                "Minecraft",
                "Minecoins и лицензия Java & Bedrock — коды, глобальный регион",
                ["Оплата в сумах", "Код сразу", "Любой регион"],
            ),
            "en": (
                "Minecraft",
                "Minecoins and the Java & Bedrock licence — codes, global region",
                ["Pay in UZS", "Instant code", "Any region"],
            ),
            "uz": (
                "Minecraft",
                "Minecoins va Java & Bedrock litsenziyasi — kodlar, global hudud",
                ["Soʻmda toʻlov", "Kod darhol", "Istalgan hudud"],
            ),
        },
    ),
    (
        "stumble-guys",
        TOP_UPS,
        22,
        {
            "ru": (
                "Stumble Guys",
                "Гемы и токены на аккаунт по User ID",
                ["Оплата в сумах", "Без пароля", "По User ID"],
            ),
            "en": (
                "Stumble Guys",
                "Gems and tokens to your account by User ID",
                ["Pay in UZS", "No password", "By User ID"],
            ),
            "uz": (
                "Stumble Guys",
                "Hisobga gem va tokenlar User ID orqali",
                ["Soʻmda toʻlov", "Parolsiz", "User ID orqali"],
            ),
        },
    ),
    (
        "marvel-rivals",
        TOP_UPS,
        23,
        {
            "ru": (
                "Marvel Rivals",
                "Lattice на аккаунт по Player ID",
                ["Оплата в сумах", "Без пароля", "По Player ID"],
            ),
            "en": (
                "Marvel Rivals",
                "Lattice to your account by Player ID",
                ["Pay in UZS", "No password", "By Player ID"],
            ),
            "uz": (
                "Marvel Rivals",
                "Hisobga Lattice Player ID orqali",
                ["Soʻmda toʻlov", "Parolsiz", "Player ID orqali"],
            ),
        },
    ),
    (
        "afk-journey",
        TOP_UPS,
        24,
        {
            "ru": (
                "AFK Journey",
                "Dragon Crystals и подписки на аккаунт по UID",
                ["Оплата в сумах", "Без пароля", "По UID"],
            ),
            "en": (
                "AFK Journey",
                "Dragon Crystals and subscriptions by account UID",
                ["Pay in UZS", "No password", "By UID"],
            ),
            "uz": (
                "AFK Journey",
                "Dragon Crystals va obunalar hisob UID orqali",
                ["Soʻmda toʻlov", "Parolsiz", "UID orqali"],
            ),
        },
    ),
]

#: ``(product_slug, brand_slug, kind, supplier_hint, field|None, {locale: name})``
PRODUCTS: list[tuple[str, str, str, str, dict[str, Any] | None, dict[str, str]]] = [
    (
        "minecraft-minecoins",
        "minecraft",
        "voucher",
        "gengine",
        None,
        {"ru": "Minecoins", "en": "Minecoins", "uz": "Minecoins"},
    ),
    (
        "minecraft-java-bedrock",
        "minecraft",
        "voucher",
        "gengine",
        None,
        {
            "ru": "Minecraft: Java & Bedrock",
            "en": "Minecraft: Java & Bedrock",
            "uz": "Minecraft: Java & Bedrock",
        },
    ),
    (
        "stumble-guys-gems",
        "stumble-guys",
        "top_up",
        "g2b",
        _id_field(
            "User ID",
            "User ID",
            "User ID",
            "Откройте Stumble Guys и зайдите в профиль — User ID показан под именем.",
            "Open Stumble Guys and go to your profile — the User ID is shown under your name.",
            "Stumble Guys ni oching va profilga kiring — User ID ism ostida koʻrsatiladi.",
        ),
        {"ru": "Гемы и токены", "en": "Gems and tokens", "uz": "Gem va tokenlar"},
    ),
    (
        "marvel-rivals-lattice",
        "marvel-rivals",
        "top_up",
        "g2b",
        _id_field(
            "Player ID",
            "Player ID",
            "Player ID",
            "Откройте Marvel Rivals и зайдите в профиль — Player ID показан рядом с ником.",
            "Open Marvel Rivals and go to your profile — the Player ID is shown next to your nickname.",
            "Marvel Rivals ni oching va profilga kiring — Player ID taxallus yonida koʻrsatiladi.",
        ),
        {"ru": "Lattice", "en": "Lattice", "uz": "Lattice"},
    ),
    (
        "afk-journey-crystals",
        "afk-journey",
        "top_up",
        "g2b",
        _id_field(
            "UID",
            "UID",
            "UID",
            "Откройте AFK Journey и зайдите в профиль — UID показан под именем персонажа.",
            "Open AFK Journey and go to your profile — the UID is shown under your character name.",
            "AFK Journey ni oching va profilga kiring — UID qahramon ismi ostida koʻrsatiladi.",
        ),
        {
            "ru": "Dragon Crystals и подписки",
            "en": "Dragon Crystals and subscriptions",
            "uz": "Dragon Crystals va obunalar",
        },
    ),
]

#: ``(sku_code, product_slug, denomination, routed supplier, cost, {supplier: external_id})``
#: Cost is the ROUTED supplier's live price, read 2026-09-24. The reserves are
#: mapped at the same time so the comparison screen has something to show.
SKUS: list[tuple[str, str, str, str, str, dict[str, str]]] = [
    # --- Minecraft: Minecoins (gengine routes; 330 is G-Engine's alone) ---
    (
        "minecraft-minecoins-330",
        "minecraft-minecoins",
        "330 Minecoins",
        "gengine",
        "1.0",
        {"gengine": "34/730"},
    ),
    (
        "minecraft-minecoins-1720",
        "minecraft-minecoins",
        "1720 Minecoins",
        "gengine",
        "6.2118",
        {
            "gengine": "34/152",
            "fzr": "minecraft_minecoins/1720_minecoins",
            "nova": "minecraft_minecoins/1720_minecoins",
        },
    ),
    (
        "minecraft-minecoins-3500",
        "minecraft-minecoins",
        "3500 Minecoins",
        "gengine",
        "12.4338",
        {
            "gengine": "34/153",
            "fzr": "minecraft_minecoins/3500_minecoins",
            "nova": "minecraft_minecoins/3500_minecoins",
        },
    ),
    (
        "minecraft-minecoins-8800",
        "minecraft-minecoins",
        "8800 Minecoins",
        "gengine",
        "45.0636",
        {
            "gengine": "34/750",
            "fzr": "minecraft_minecoins/8800_minecoins",
            "nova": "minecraft_minecoins/8800_minecoins",
        },
    ),
    # --- Minecraft: the game licence ---
    (
        "minecraft-java-bedrock-pc",
        "minecraft-java-bedrock",
        "Java & Bedrock Edition",
        "gengine",
        "18.0234",
        {
            "gengine": "2/2",
            "fzr": "minecraft_java_bedrock_global/java_bedrock_pc",
            "nova": "minecraft_java_bedrock_global/java_bedrock_pc",
        },
    ),
    # --- Stumble Guys ---
    (
        "stumble-250-gems",
        "stumble-guys-gems",
        "250 Gems",
        "g2b",
        "0.908",
        {
            "g2b": "stumble_guys/1979",
            "fzr": "stumble_guys/250_gems",
            "nova": "stumble_guys/250_gems",
        },
    ),
    (
        "stumble-800-gems",
        "stumble-guys-gems",
        "800 Gems",
        "g2b",
        "2.04",
        {
            "g2b": "stumble_guys/1980",
            "fzr": "stumble_guys/800_gems",
            "nova": "stumble_guys/800_gems",
        },
    ),
    (
        "stumble-1600-gems",
        "stumble-guys-gems",
        "1600 Gems + 75 Tokens",
        "g2b",
        "3.407",
        {
            "g2b": "stumble_guys/1982",
            "fzr": "stumble_guys/1600_gems_75_tokens",
            "nova": "stumble_guys/1600_gems_75_tokens",
        },
    ),
    (
        "stumble-5000-gems",
        "stumble-guys-gems",
        "5000 Gems + 275 Tokens",
        "g2b",
        "8.405",
        {
            "g2b": "stumble_guys/1983",
            "fzr": "stumble_guys/5000_gems_275_tokens",
            "nova": "stumble_guys/5000_gems_275_tokens",
        },
    ),
    (
        "stumble-120-tokens",
        "stumble-guys-gems",
        "120 Tokens",
        "g2b",
        "2.499",
        {
            "g2b": "stumble_guys/1984",
            "fzr": "stumble_guys/120_tokens",
            "nova": "stumble_guys/120_tokens",
        },
    ),
    (
        "stumble-1300-tokens",
        "stumble-guys-gems",
        "1300 Tokens",
        "g2b",
        "20.9",
        {
            "g2b": "stumble_guys/1981",
            "fzr": "stumble_guys/1300_tokens",
            "nova": "stumble_guys/1300_tokens",
        },
    ),
    # --- Marvel Rivals ---
    (
        "marvel-100-lattices",
        "marvel-rivals-lattice",
        "100 Lattices",
        "g2b",
        "0.877",
        {
            "g2b": "marvelrivals/1637",
            "fzr": "marvel_rivals/100_lattices",
            "nova": "marvel_rivals/100_lattices",
        },
    ),
    (
        "marvel-500-lattices",
        "marvel-rivals-lattice",
        "500 Lattices",
        "g2b",
        "4.396",
        {
            "g2b": "marvelrivals/1675",
            "fzr": "marvel_rivals/500_lattices",
            "nova": "marvel_rivals/500_lattices",
        },
    ),
    (
        "marvel-1000-lattices",
        "marvel-rivals-lattice",
        "1000 Lattices",
        "g2b",
        "8.803",
        {
            "g2b": "marvelrivals/1676",
            "fzr": "marvel_rivals/1000_lattices",
            "nova": "marvel_rivals/1000_lattices",
        },
    ),
    (
        "marvel-2180-lattices",
        "marvel-rivals-lattice",
        "2180 Lattices",
        "g2b",
        "17.595",
        {
            "g2b": "marvelrivals/1677",
            "fzr": "marvel_rivals/2180_lattices",
            "nova": "marvel_rivals/2180_lattices",
        },
    ),
    (
        "marvel-5680-lattices",
        "marvel-rivals-lattice",
        "5680 Lattices",
        "g2b",
        "43.982",
        {
            "g2b": "marvelrivals/1678",
            "fzr": "marvel_rivals/5680_lattices",
            "nova": "marvel_rivals/5680_lattices",
        },
    ),
    (
        "marvel-11680-lattices",
        "marvel-rivals-lattice",
        "11680 Lattices",
        "g2b",
        "87.965",
        {
            "g2b": "marvelrivals/1679",
            "fzr": "marvel_rivals/11680_lattices",
            "nova": "marvel_rivals/11680_lattices",
        },
    ),
    # --- AFK Journey ---
    (
        "afk-21-crystals",
        "afk-journey-crystals",
        "21 Dragon Crystals",
        "g2b",
        "0.857",
        {
            "g2b": "afkjourney/577",
            "fzr": "afk_journey/21_dragon_crystals",
            "nova": "afk_journey/21_dragon_crystals",
        },
    ),
    (
        "afk-126-crystals",
        "afk-journey-crystals",
        "126 Dragon Crystals",
        "g2b",
        "4.253",
        {
            "g2b": "afkjourney/583",
            "fzr": "afk_journey/126_dragon_crystals",
            "nova": "afk_journey/126_dragon_crystals",
        },
    ),
    (
        "afk-294-crystals",
        "afk-journey-crystals",
        "294 Dragon Crystals",
        "g2b",
        "8.558",
        {
            "g2b": "afkjourney/578",
            "fzr": "afk_journey/294_dragon_crystals",
            "nova": "afk_journey/294_dragon_crystals",
        },
    ),
    (
        "afk-588-crystals",
        "afk-journey-crystals",
        "588 Dragon Crystals",
        "g2b",
        "17.717",
        {
            "g2b": "afkjourney/579",
            "fzr": "afk_journey/588_dragon_crystals",
            "nova": "afk_journey/588_dragon_crystals",
        },
    ),
    (
        "afk-1554-crystals",
        "afk-journey-crystals",
        "1554 Dragon Crystals",
        "g2b",
        "43.024",
        {
            "g2b": "afkjourney/580",
            "fzr": "afk_journey/1554_dragon_crystals",
            "nova": "afk_journey/1554_dragon_crystals",
        },
    ),
    (
        "afk-3150-crystals",
        "afk-journey-crystals",
        "3150 Dragon Crystals",
        "g2b",
        "86.098",
        {
            "g2b": "afkjourney/584",
            "fzr": "afk_journey/3150_dragon_crystals",
            "nova": "afk_journey/3150_dragon_crystals",
        },
    ),
    (
        "afk-esperia-classic",
        "afk-journey-crystals",
        "Esperia Monthly — Classic",
        "g2b",
        "4.253",
        {
            "g2b": "afkjourney/585",
            "fzr": "afk_journey/esperia_monthly_classic_gazette",
            "nova": "afk_journey/esperia_monthly_classic_gazette",
        },
    ),
    (
        "afk-esperia-premium",
        "afk-journey-crystals",
        "Esperia Monthly — Premium",
        "g2b",
        "13.413",
        {
            "g2b": "afkjourney/581",
            "fzr": "afk_journey/esperia_monthly_premium_gazette",
            "nova": "afk_journey/esperia_monthly_premium_gazette",
        },
    ),
    (
        "afk-growth-bundle",
        "afk-journey-crystals",
        "Growth Bundle",
        "g2b",
        "25.786",
        {
            "g2b": "afkjourney/582",
            "fzr": "afk_journey/growth_bundle",
            "nova": "afk_journey/growth_bundle",
        },
    ),
]


def _price(cost: Decimal, margin: Decimal) -> Decimal:
    """Cost plus margin, to the cent, half-up — how every other rung rounds."""
    return (cost * (Decimal("1") + margin / Decimal("100"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _existing(
    session: Any, model: Any, slugs: list[str], attr: str = "slug"
) -> dict[str, Any]:
    rows = (await session.execute(select(model).where(getattr(model, attr).in_(slugs)))).scalars()
    return {getattr(r, attr): r for r in rows}


async def main() -> None:  # noqa: PLR0912, PLR0915 -- one linear pass, read top to bottom
    factory = get_session_factory()
    async with factory() as session:
        brands = await _existing(session, Brand, [b[0] for b in BRANDS])
        for slug, category_id, sort_order, tr in BRANDS:
            if slug in brands:
                print(f"  бренд  {slug:16s} уже есть, пропуск")
                continue
            state = "включён" if BRAND_ACTIVE else "ВЫКЛЮЧЕН"
            print(f"  бренд  {slug:16s} создать  (sort={sort_order}, {state})")
            if not APPLY:
                continue
            row = await cat.create_brand(
                session,
                cs.BrandCreate(
                    slug=slug,
                    category_id=category_id,
                    sort_order=sort_order,
                    active=BRAND_ACTIVE,
                    translations=[
                        cs.TranslationIn(
                            locale=loc, name=name, short_description=short, highlights=chips
                        )
                        for loc, (name, short, chips) in tr.items()
                    ],
                ),
            )
            # Not on BrandCreate; every other brand of ours is B2B-visible.
            row.visible_b2b = True
            brands[slug] = row
        if APPLY:
            await session.flush()

        products = await _existing(session, Product, [p[0] for p in PRODUCTS])
        for slug, brand_slug, kind, hint, field, names in PRODUCTS:
            if slug in products:
                print(f"  продукт {slug:26s} уже есть, пропуск")
                continue
            print(f"  продукт {slug:26s} создать  kind={kind} поле={'да' if field else 'нет'}")
            if not APPLY:
                continue
            brand = brands.get(brand_slug)
            if brand is None:
                print(f"  продукт {slug:26s} ПРОПУЩЕН — нет бренда {brand_slug}")
                continue
            products[slug] = await cat.create_product(
                session,
                cs.ProductCreate(
                    slug=slug,
                    brand_id=brand.id,
                    kind=kind,
                    supplier_hint=hint,
                    required_fields=[field] if field else [],
                    translations=[
                        cs.TranslationIn(locale=loc, name=name) for loc, name in names.items()
                    ],
                ),
            )
        if APPLY:
            await session.flush()

        skus = await _existing(session, Sku, [s[0] for s in SKUS], attr="sku_code")
        # Kinds come from the table above, not from the freshly created rows:
        # a dry run creates nothing, and a preview that cannot price anything
        # is not a preview.
        kinds = {slug: kind for slug, _b, kind, _h, _f, _n in PRODUCTS}
        made = mapped = 0
        for order, (code, product_slug, denom, routed, cost_s, ext) in enumerate(SKUS):
            cost = Decimal(cost_s)
            margin = MARGIN_VOUCHER if kinds[product_slug] == "voucher" else MARGIN_GAME
            price = _price(cost, margin)
            sku = skus.get(code)
            if sku is None:
                print(
                    f"  sku    {code:28s} {denom[:26]:26s} cost={cost:8} -> ${price:7} "
                    f"({margin}%) маршрут={routed}"
                )
                product = products.get(product_slug)
                if APPLY and product is not None:
                    sku = await cat.create_sku(
                        session,
                        cs.SkuCreate(
                            product_id=product.id,
                            sku_code=code,
                            denomination=denom,
                            region="GLOBAL",
                            price_usd=price,
                            cost_usdt=cost,
                            margin_percent=margin,
                            sort_order=order,
                        ),
                    )
                    sku.visible_b2b = True
                    skus[code] = sku
                    made += 1
            else:
                print(f"  sku    {code:28s} уже есть, цена не трогается")
            product = products.get(product_slug)
            if not APPLY or sku is None or product is None:
                continue
            await session.flush()
            for supplier, ref in ext.items():
                product_id, _, variant_id = ref.partition("/")
                await upsert_mapping(
                    session,
                    MappingUpsert(
                        sku_id=sku.id,
                        supplier_slug=supplier,
                        kind="voucher" if kinds[product_slug] == "voucher" else "game",
                        external_product_id=product_id,
                        external_variant_id=variant_id or None,
                        quantity=1,
                        extra={},
                        is_active=True,
                        updated_by=ADMIN_ID,
                    ),
                )
                mapped += 1

        if APPLY:
            await session.commit()
            print(f"\nЗАПИСАНО: SKU создано {made}, маппингов {mapped}")
            print("Маршрут везде авто — резервы (fzr, nova) не выбираются сами.")
            print("Бренды ВЫКЛЮЧЕНЫ. Перед включением: логотипы, hero и проверка")
            print("подсказок «где найти ID» на живых играх.")
        else:
            print(f"\nСУХОЙ ПРОГОН. APPLY=1 чтобы записать. Всего SKU в плане: {len(SKUS)}")


asyncio.run(main())
