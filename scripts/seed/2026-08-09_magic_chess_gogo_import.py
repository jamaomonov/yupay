"""Onboard Magic Chess: Go Go into the catalog from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-09_magic_chess_gogo_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-09_magic_chess_gogo_import.py

Same shape as the Mobile Legends onboarding, and for the same reason: Moonton
runs a separate Russian region alongside the global one, both take the same two
inputs, and buying the wrong one produces an order we take money for and cannot
deliver. [ADR-0048](../../docs/decisions/0048-mobile-legends-region-split.md)
holds the reasoning; this script applies it to a second game.

**The variants.** G2B lists five (live ``/games/{code}/fields`` notes, 2026-08-09):

    magic_chess_gogo  "Available for all users"          — 20 denominations
    magic_chest_gogo  "Available for all users"          — 20 denominations
    mcgg_ru           "only for all Russian MCGG users"  — 12 denominations
    mcgg_my           "only for all Malaysian MCGG users"
    mcgg_ph           "only for all Philippines MCGG users"

The first two are the same product listed twice: identical denominations at
identical costs, differing only in G2B's internal catalogue ids. ``magic_chest_gogo``
(game id 75) has a typo in its code — "chest" for "chess" — and ``magic_chess_gogo``
(id 129) is the later, correctly spelled entry. We map the spelled-correctly one
on the assumption the typo'd one is the legacy alias kept for existing
integrations. If orders against it ever start failing, the other code is a
one-line change here.

We sell ``magic_chess_gogo`` (Uzbekistan and the CIS) and ``mcgg_ru`` (Russia).

The two event bundles the global catalogue carries — "Battle for Discounts" and
"Lukas's Battle Bounty" — are left out. They cost the same as 55 diamonds but
their names say nothing about what a customer receives, and event items come and
go upstream; a SKU that stops existing is a failed order.

This file duplicates the structure of the Mobile Legends script rather than
sharing a helper with it, because it is delivered by piping a single file into
the container's stdin — there is no sibling module to import.

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

BRAND_SLUG = "magic-chess-gogo"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------
#
# Keys are `player_id` and `server` — what the G2B fulfiller reads out of
# `fulfillment_data`. Naming them `userid`/`serverid` after G2B's own API would
# silently drop the server and fail every order with an HTTP 400.
#
# Where the ID lives is verified, not assumed: tap the avatar in the upper-left
# corner and the Game ID and Server are shown together, in the same
# `123456789 (1234)` form Mobile Legends uses.

_PLAYER_ID_HELP = {
    "ru": (
        "Откройте Magic Chess: Go Go и нажмите на аватар в левом верхнем углу.\n"
        "На экране профиля показаны Game ID и сервер в виде «123456789 (1234)» — "
        "первое число это ID игрока, число в скобках это ID сервера.\n"
        "Скопируйте оба значения точно, без пробелов.\n"
        "Пароль не нужен — пополнение идёт по публичному ID."
    ),
    "en": (
        "Open Magic Chess: Go Go and tap your avatar in the upper-left corner.\n"
        "The profile screen shows your Game ID and server as “123456789 (1234)” — the "
        "first number is your player ID, the number in brackets is your server ID.\n"
        "Copy both exactly, with no spaces.\n"
        "No password needed — top-up is by public ID."
    ),
    "uz": (
        "Magic Chess: Go Go ni oching va chap yuqori burchakdagi avatarni bosing.\n"
        "Profil ekranida Game ID va server «123456789 (1234)» koʻrinishida "
        "koʻrsatiladi — birinchi raqam oʻyinchi ID, qavs ichidagi raqam server ID.\n"
        "Ikkalasini ham boʻshliqsiz, aniq nusxalang.\n"
        "Parol kerak emas — toʻldirish ommaviy ID orqali."
    ),
}

_SERVER_HELP = {
    "ru": (
        "ID сервера (Zone ID) — это число в скобках рядом с Game ID, обычно 4 цифры.\n"
        "Например, в «123456789 (1234)» ID сервера это 1234.\n"
        "Без него алмазы не найдут ваш аккаунт."
    ),
    "en": (
        "The server ID (Zone ID) is the number in brackets next to your Game ID — "
        "usually 4 digits.\n"
        "In “123456789 (1234)”, the server ID is 1234.\n"
        "Without it the diamonds cannot find your account."
    ),
    "uz": (
        "Server ID (Zone ID) — Game ID yonidagi qavs ichidagi raqam, odatda 4 xonali.\n"
        "«123456789 (1234)» misolida server ID — 1234.\n"
        "Usiz olmoslar hisobingizni topa olmaydi."
    ),
}


def _required_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID"},
            "required": True,
            "pattern": "^[0-9]{5,20}$",
            "placeholder": {"ru": "123456789", "en": "123456789", "uz": "123456789"},
            "help_text": _PLAYER_ID_HELP,
            # The region guard: G2B's checkPlayerId runs against the same
            # game_code this product is mapped to, so a global id entered under
            # the Russian product returns no nickname before any money moves.
            "check": {"provider": "g2b", "server_field": "server"},
        },
        {
            "key": "server",
            "type": "text",
            "label": {"ru": "ID сервера", "en": "Server ID", "uz": "Server ID"},
            "required": True,
            "pattern": "^[0-9]{3,6}$",
            "placeholder": {"ru": "1234", "en": "1234", "uz": "1234"},
            "help_text": _SERVER_HELP,
        },
    ]


# --- denominations ---------------------------------------------------------
#
# `catalogue_name` must match G2B's catalogue entry byte for byte. `cost_usdt` is
# what G2B quoted on 2026-08-09; the hourly refresh-all-prices job owns it after
# that, so these only seed the first sell price. Cheapest first — `import_game`
# takes sort_order from this position, so request order is the storefront ladder.

GLOBAL_DENOMS: list[tuple[str, str, str]] = [
    ("55", "55 Diamonds", "0.785"),
    ("86", "86 Diamonds", "1.224"),
    ("Weekly Card", "Weekly Card", "1.958"),
    ("165", "165 Diamonds", "2.356"),
    ("275", "275 Diamonds", "3.927"),
    ("565", "565 Diamonds", "7.844"),
    ("706", "706 Diamonds", "9.802"),
    ("1060", "1060 Diamonds", "14.902"),
    ("1346", "1346 Diamonds", "18.38"),
    ("2195", "2195 Diamonds", "29.417"),
    ("3688", "3688 Diamonds", "49.021"),
    ("5532", "5532 Diamonds", "73.532"),
    ("9288", "9288 Diamonds", "122.563"),
]

RU_DENOMS: list[tuple[str, str, str]] = [
    ("55", "55 Diamonds", "0.979"),
    ("Weekly Diamond Pass", "Weekly Diamond Pass", "1.877"),
    ("165", "165 Diamonds", "2.938"),
    ("275", "275 Diamonds", "4.896"),
    ("565", "565 Diamonds", "9.853"),
    ("1060", "1060 Diamonds", "18.666"),
    ("1155", "1155 Diamonds", "19.768"),
    ("1765", "1765 Diamonds", "29.56"),
    ("2975", "2975 Diamonds", "49.327"),
    ("6000", "6000 Diamonds", "98.532"),
]


def _sku_code(prefix: str, catalogue_name: str) -> str:
    """`mcgg-55`, `mcgg-weekly-card`, `mcgg_ru-weekly-diamond-pass`.

    Derived from the catalogue name rather than hand-written so a denomination
    added to the lists above cannot silently collide with an existing code —
    `Sku.sku_code` is globally unique and a collision is reported as a skip, not
    an error, which would look like a successful import that quietly did less.
    """
    return f"{prefix}-{catalogue_name.lower().replace(' ', '-')}"


def _denoms(prefix: str, rows: list[tuple[str, str, str]], region: str) -> list[DenomImportIn]:
    return [
        DenomImportIn(
            catalogue_name=name,
            denomination=label,
            sku_code=_sku_code(prefix, name),
            cost_usdt=Decimal(cost),
            region=region,
        )
        for name, label, cost in rows
    ]


PRODUCTS = [
    {
        "game_code": "magic_chess_gogo",
        "sku_prefix": "mcgg",
        "slug": "mcgg-diamonds",
        "name": "Алмазы — глобальный аккаунт",
        "region": "global",
        "denoms": GLOBAL_DENOMS,
    },
    {
        "game_code": "mcgg_ru",
        "sku_prefix": "mcgg_ru",
        "slug": "mcgg-diamonds-ru",
        "name": "Алмазы — российский аккаунт",
        "region": "ru",
        "denoms": RU_DENOMS,
    },
]


async def _games_category_id(session: Any) -> str:
    row = (await session.execute(select(Category).where(Category.slug == "games"))).scalar_one()
    return str(row.id)


async def _existing_brand_id(session: Any) -> str | None:
    row = (
        await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
    ).scalar_one_or_none()
    return None if row is None else str(row.id)


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
        category_id = await _games_category_id(session)
        brand_id = await _existing_brand_id(session)
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
                game_code=str(spec["game_code"]),
                target="new_brand" if brand_id is None else "existing_brand",
                brand_id=brand_id,
                new_brand=(
                    None
                    if brand_id is not None
                    else NewBrandIn(
                        slug=BRAND_SLUG,
                        category_id=category_id,
                        name="Magic Chess: Go Go",
                    )
                ),
                product=ProductImportIn(
                    slug=slug,
                    name=str(spec["name"]),
                    required_fields=_required_fields(),  # type: ignore[arg-type]
                ),
                margin_percent=MARGIN_PERCENT,
                denominations=_denoms(
                    str(spec["sku_prefix"]),
                    spec["denoms"],  # type: ignore[arg-type]
                    str(spec["region"]),
                ),
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
