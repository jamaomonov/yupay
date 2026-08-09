"""Onboard Honkai: Star Rail into the catalog from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-09_honkai_star_rail_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-09_honkai_star_rail_import.py

Structured to mirror Genshin, the miHoYo game already in the catalog: a currency
product beside a monthly-pass product (`genshin-crystals` + `genshin-welkin`),
UID plus a server picker, no region lock beyond mainland China.

**Why not Honkai Impact 3rd.** It was the game originally asked for. G2B carries
exactly one HI3 product and it is flagged "Available for SEA users", while HI3
runs a separate client per server (China / Japan / TW-KR-SEA / EU / NA) with no
CIS server at all — players here are on EU. Listing a SEA-only product would
have failed for most of the audience, so it was skipped in favour of this.

**No player check on this product, deliberately.** G2B's ``checkPlayerId``
does not validate miHoYo ids: for both ``genshin`` and ``honkai_star_rail`` it
answers *any* input — invented UID, invented server — with
``{"valid": "valid", "name": "No validation required"}``. Wiring
``required_fields[0].check`` would put that string on screen where the storefront
shows a confirmed nickname, so a customer would read "verified" from a check
that verified nothing. Genshin already omits it; this follows.

**Server values come from G2B's own ``/games/servers``**, which returns
``America``, ``Asia``, ``Europe``, ``TW_HK_MO`` for this game. Worth knowing:
our existing Genshin product uses miHoYo's internal codes (``os_euro`` &c.)
instead, and G2B publishes the same four names for Genshin too. Since
``checkPlayerId`` rubber-stamps everything, neither form can be verified without
placing a real order — so this new product uses what the supplier publishes, and
the Genshin discrepancy is worth checking against delivered orders in the admin.

Idempotent: an existing brand is reused, and ``import_game`` skips any
``sku_code`` that already exists (reported in ``skipped``).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.integrations.schemas import (
    DenomImportIn,
    GameImportIn,
    NewBrandIn,
    ProductImportIn,
)
from yupay.modules.integrations.service import import_game

BRAND_SLUG = "honkai-star-rail"
GAME_CODE = "honkai_star_rail"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------
#
# Keys are `player_id` and `server` — what the G2B fulfiller reads out of
# `fulfillment_data`. The server values are G2B's published ones; the labels are
# ours.

_PLAYER_ID_HELP = {
    "ru": (
        "UID показан в левом нижнем углу экрана в игре — это самый быстрый способ.\n"
        "Также его видно в меню телефона и в «Settings» → «Account» → «User ID».\n"
        "UID состоит только из цифр; ник вводить не нужно.\n"
        "Пароль не нужен — пополнение идёт по публичному UID."
    ),
    "en": (
        "The UID is shown in the bottom-left corner of the screen in game — the "
        "quickest place to read it.\n"
        "It is also in the phone menu and under Settings → Account → User ID.\n"
        "The UID is digits only; do not enter your nickname.\n"
        "No password needed — top-up is by public UID."
    ),
    "uz": (
        "UID oʻyinda ekranning chap pastki burchagida koʻrsatiladi — eng tez yoʻl.\n"
        "Shuningdek, telefon menyusida va «Settings» → «Account» → «User ID» "
        "boʻlimida bor.\n"
        "UID faqat raqamlardan iborat; nik kiritish shart emas.\n"
        "Parol kerak emas — toʻldirish ommaviy UID orqali."
    ),
}

_SERVER_HELP = {
    "ru": (
        "Сервер выбирается при создании аккаунта и виден на экране входа рядом с "
        "именем аккаунта.\n"
        "Игроки из Узбекистана и СНГ чаще всего играют на Europe.\n"
        "Указывайте тот сервер, на котором находится ваш UID — на другом "
        "пополнение не найдёт аккаунт."
    ),
    "en": (
        "The server is chosen when the account is created and is shown on the login "
        "screen next to the account name.\n"
        "Players from Uzbekistan and the CIS are most often on Europe.\n"
        "Pick the server your UID actually lives on — on another one the top-up "
        "will not find the account."
    ),
    "uz": (
        "Server akkaunt yaratilganda tanlanadi va kirish ekranida akkaunt nomi "
        "yonida koʻrsatiladi.\n"
        "Oʻzbekiston va MDH oʻyinchilari koʻpincha Europe serverida.\n"
        "UID joylashgan serverni koʻrsating — boshqasida toʻldirish hisobni "
        "topa olmaydi."
    ),
}

_SERVERS = [
    ("Europe", {"ru": "Европа", "en": "Europe", "uz": "Yevropa"}),
    ("America", {"ru": "Америка", "en": "America", "uz": "Amerika"}),
    ("Asia", {"ru": "Азия", "en": "Asia", "uz": "Osiyo"}),
    ("TW_HK_MO", {"ru": "TW / HK / MO", "en": "TW / HK / MO", "uz": "TW / HK / MO"}),
]


def _required_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "UID", "en": "UID", "uz": "UID"},
            "required": True,
            "pattern": "^[0-9]{5,20}$",
            "placeholder": {"ru": "800000000", "en": "800000000", "uz": "800000000"},
            "help_text": _PLAYER_ID_HELP,
        },
        {
            "key": "server",
            "type": "select",
            "label": {"ru": "Сервер", "en": "Server", "uz": "Server"},
            "required": True,
            "help_text": _SERVER_HELP,
            # Europe first: it is where most of this storefront's players are, and
            # the first option is the one a hurried customer accepts.
            "options": [{"value": value, "label": label} for value, label in _SERVERS],
        },
    ]


# --- denominations ---------------------------------------------------------
#
# `catalogue_name` must match G2B's catalogue entry byte for byte. `cost_usdt` is
# what G2B quoted on 2026-08-09; the hourly refresh-all-prices job owns it after
# that. Cheapest first — `import_game` takes sort_order from this position.

SHARD_DENOMS: list[tuple[str, str, str]] = [
    ("60", "60 Oneiric Shards", "1"),
    ("330", "330 Oneiric Shards", "5"),
    ("1090", "1090 Oneiric Shards", "15"),
    ("2240", "2240 Oneiric Shards", "30"),
    ("3880", "3880 Oneiric Shards", "50"),
    ("8080", "8080 Oneiric Shards", "100"),
]

PASS_DENOMS: list[tuple[str, str, str]] = [
    ("Express", "Express Supply Pass", "5"),
]


def _denoms(rows: list[tuple[str, str, str]]) -> list[DenomImportIn]:
    return [
        DenomImportIn(
            catalogue_name=name,
            denomination=label,
            sku_code=f"hsr-{name.lower()}",
            cost_usdt=Decimal(cost),
        )
        for name, label, cost in rows
    ]


PRODUCTS = [
    {"slug": "hsr-oneiric-shards", "name": "Oneiric Shards", "denoms": SHARD_DENOMS},
    {"slug": "hsr-express-pass", "name": "Express Supply Pass", "denoms": PASS_DENOMS},
]


async def _games_category_id(session: Any) -> str:
    row = (await session.execute(select(Category).where(Category.slug == "games"))).scalar_one()
    return str(row.id)


async def _order_skus_by_price(session: Any, product_id: str) -> int:
    """Give the denominations a price ladder.

    Redundant against a current API — ``import_game`` now assigns ``sort_order``
    from the request position, and the lists above are already cheapest-first.
    It stays because this script has to run against an API container that has
    not been redeployed yet, where every imported SKU still lands on the column
    default of 0 and the storefront renders them in whatever order the database
    returns. Idempotent either way: it writes the order the ladder already has.
    """
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


async def main() -> None:
    async with get_session_factory()() as session:
        brand = (
            await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
        ).scalar_one_or_none()
        brand_id = None if brand is None else str(brand.id)
        print(f"brand {BRAND_SLUG}: {'reusing ' + brand_id if brand_id else 'creating'}")

        for spec in PRODUCTS:
            slug = str(spec["slug"])
            existing_product = (
                await session.execute(select(Product).where(Product.slug == slug))
            ).scalar_one_or_none()
            if existing_product is not None:
                print(f"  {slug}: already exists ({existing_product.id}) — skipping import")
                await _order_skus_by_price(session, str(existing_product.id))
                continue

            payload = GameImportIn(
                game_code=GAME_CODE,
                target="new_brand" if brand_id is None else "existing_brand",
                brand_id=brand_id,
                new_brand=(
                    None
                    if brand_id is not None
                    else NewBrandIn(
                        slug=BRAND_SLUG,
                        category_id=await _games_category_id(session),
                        name="Honkai: Star Rail",
                    )
                ),
                product=ProductImportIn(
                    slug=slug,
                    name=str(spec["name"]),
                    required_fields=_required_fields(),  # type: ignore[arg-type]
                ),
                margin_percent=MARGIN_PERCENT,
                denominations=_denoms(spec["denoms"]),  # type: ignore[arg-type]
            )
            result = await import_game(session, payload, admin_id=ADMIN_ID)
            brand_id = result.brand_id
            ordered = await _order_skus_by_price(session, result.product_id)
            print(
                f"  {slug}: brand={result.brand_id} product={result.product_id} "
                f"skus={result.created_skus} mappings={result.created_mappings} "
                f"skipped={result.skipped} ordered={ordered}"
            )

        await session.commit()
        print("committed")


asyncio.run(main())
