"""Onboard Mobile Legends: Bang Bang into the catalog from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-09_mobile_legends_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-09_mobile_legends_import.py

Why a script and not the admin wizard: MLBB is not one game at G2B but seven
region-locked products, and picking the wrong one produces an order that takes
the customer's money and cannot be delivered. Which two we sell, and the exact
denominations, are a decision worth reviewing in a diff rather than
reconstructing from clicks. It calls the same ``integrations.service.import_game``
the wizard's endpoint calls, so the catalog write path is identical.

**The region split.** G2B's eligibility matrix (verified against the live
``/games/{code}/fields`` notes on 2026-08-09):

    mlbb        CIS + rest of world, NOT Russia/SG/MY/PH/VN/Indonesia
    mlbb_ru     Russia + CIS only
    mlbb_global Indonesia (G2B's note) — the cheap ladder is on ``mlbb``
    mlbb_tr     Turkey only
    mlbb_exclusive Philippines only
    mlbb_special everywhere except Indonesia and Russia, ~27% dearer per diamond
    mlbb_br     CIS + world, but non-BR accounts receive 10% fewer diamonds

We sell ``mlbb`` (Uzbekistan and the rest of the CIS, cheapest per diamond) and
``mlbb_ru`` (Russia, and CIS players whose account sits on the Russian region).
``mlbb_br`` is excluded on purpose: silently short-changing a customer 10% of
what the label promises is not a discount, it is a complaint.

A player's region is fixed when the account is created and Moonton gives no way
to move it, so this is the customer's one unrecoverable choice at checkout.
Three things guard it, in increasing order of reliability: the product name says
which account it is for, the field help text says how to tell, and
``required_fields[0].check`` runs G2B's ``checkPlayerId`` live — a global id
entered against the Russian product comes back invalid before any money moves.

Idempotent: an existing brand is reused, and ``import_game`` skips any
``sku_code`` that already exists (reported in ``skipped``). Re-running after
adding a denomination below imports only the new one.
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

BRAND_SLUG = "mobile-legends"
MARGIN_PERCENT = Decimal("20")

# The admin this import is attributed to in the mapping audit fields. The
# bootstrap admin exists in every environment; override via ADMIN_ID if you want
# the audit trail to name a person.
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------
#
# Keys are `player_id` and `server` because that is what the G2B fulfiller reads
# out of `fulfillment_data` (suppliers/g2b.py). Naming them `userid`/`serverid`
# after G2B's own API would silently drop the server and every order would fail
# with an HTTP 400.

_PLAYER_ID_HELP = {
    "ru": (
        "Откройте Mobile Legends и нажмите на аватар в левом верхнем углу лобби.\n"
        "В профиле под ником указано «ID: 123456789 (1234)» — первое число это ID "
        "игрока, число в скобках это ID сервера.\n"
        "Скопируйте оба значения точно, без пробелов.\n"
        "Пароль не нужен — пополнение идёт по публичному ID."
    ),
    "en": (
        "Open Mobile Legends and tap your avatar in the top-left corner of the lobby.\n"
        "In your profile, under your nickname, you will see “ID: 123456789 (1234)” — the "
        "first number is your player ID, the number in brackets is your server ID.\n"
        "Copy both exactly, with no spaces.\n"
        "No password needed — top-up is by public ID."
    ),
    "uz": (
        "Mobile Legends ni oching va lobbi chap yuqori burchagidagi avatarni bosing.\n"
        "Profilda taxallus ostida «ID: 123456789 (1234)» koʻrsatiladi — birinchi raqam "
        "oʻyinchi ID, qavs ichidagi raqam server ID.\n"
        "Ikkalasini ham boʻshliqsiz, aniq nusxalang.\n"
        "Parol kerak emas — toʻldirish ommaviy ID orqali."
    ),
}

_SERVER_HELP = {
    "ru": (
        "ID сервера (Zone ID) — это число в скобках рядом с вашим ID в профиле, "
        "обычно 4 цифры.\n"
        "Например, в «ID: 123456789 (1234)» ID сервера это 1234.\n"
        "Без него алмазы не найдут ваш аккаунт."
    ),
    "en": (
        "The server ID (Zone ID) is the number in brackets next to your ID in the "
        "profile — usually 4 digits.\n"
        "In “ID: 123456789 (1234)”, the server ID is 1234.\n"
        "Without it the diamonds cannot find your account."
    ),
    "uz": (
        "Server ID (Zone ID) — profilda ID yonidagi qavs ichidagi raqam, odatda "
        "4 xonali.\n"
        "«ID: 123456789 (1234)» misolida server ID — 1234.\n"
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
            # Live verification against the *same* game_code this product is
            # mapped to. This is what turns "did I pick the right region?" from
            # a guess into an answer: the nickname comes back, or it does not.
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
# `catalogue_name` must match G2B's catalogue entry byte for byte — it is what
# the mapping sends back as `external_variant_id`. `cost_usdt` is the amount G2B
# quoted on 2026-08-09; the hourly refresh-all-prices job owns it from then on,
# so these values only seed the first sell price.

# Listed cheapest first: `import_game` assigns sort_order from this position, so
# the request order *is* the storefront ladder. The passes sit at their price
# rather than in a block of their own — the customer is comparing what a given
# sum buys, and a pass costing less than the next diamond tier belongs there.

GLOBAL_DENOMS: list[tuple[str, str, str]] = [
    ("55", "55 Diamonds", "0.755"),
    ("86", "86 Diamonds", "1.193"),
    ("Weekly", "Weekly Diamond Pass", "1.479"),
    ("165", "165 Diamonds", "2.285"),
    ("275", "275 Diamonds", "3.662"),
    ("429", "429 Diamonds", "5.794"),
    ("565", "565 Diamonds", "7.517"),
    ("Twilight", "Twilight Pass", "7.854"),
    ("878", "878 Diamonds", "11.74"),
    ("1060", "1060 Diamonds", "14.209"),
    ("1412", "1412 Diamonds", "18.737"),
    ("2195", "2195 Diamonds", "28.346"),
    ("3688", "3688 Diamonds", "47.297"),
]

RU_DENOMS: list[tuple[str, str, str]] = [
    ("35", "35 Diamonds", "0.622"),
    ("55", "55 Diamonds", "0.979"),
    ("Weekly", "Weekly Diamond Pass", "1.969"),
    ("165", "165 Diamonds", "2.938"),
    ("275", "275 Diamonds", "4.896"),
    ("565", "565 Diamonds", "9.853"),
    ("1155", "1155 Diamonds", "19.768"),
    ("1765", "1765 Diamonds", "29.56"),
    ("2975", "2975 Diamonds", "49.327"),
    ("6000", "6000 Diamonds", "98.532"),
]


def _denoms(game_code: str, rows: list[tuple[str, str, str]], region: str) -> list[DenomImportIn]:
    return [
        DenomImportIn(
            catalogue_name=name,
            denomination=label,
            sku_code=f"{game_code}-{name.lower()}",
            cost_usdt=Decimal(cost),
            region=region,
        )
        for name, label, cost in rows
    ]


PRODUCTS = [
    {
        "game_code": "mlbb",
        "slug": "mlbb-diamonds",
        "name": "Алмазы — глобальный аккаунт",
        "region": "global",
        "denoms": GLOBAL_DENOMS,
    },
    {
        "game_code": "mlbb_ru",
        "slug": "mlbb-diamonds-ru",
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
            game_code = str(spec["game_code"])
            slug = str(spec["slug"])
            existing_product = (
                await session.execute(select(Product).where(Product.slug == slug))
            ).scalar_one_or_none()
            if existing_product is not None:
                print(f"  {slug}: already exists ({existing_product.id}) — skipping import")
                await _order_skus_by_price(session, str(existing_product.id))
                continue

            payload = GameImportIn(
                game_code=game_code,
                target="new_brand" if brand_id is None else "existing_brand",
                brand_id=brand_id,
                new_brand=(
                    None
                    if brand_id is not None
                    else NewBrandIn(
                        slug=BRAND_SLUG,
                        category_id=category_id,
                        name="Mobile Legends",
                    )
                ),
                product=ProductImportIn(
                    slug=slug,
                    name=str(spec["name"]),
                    required_fields=_required_fields(),  # type: ignore[arg-type]
                ),
                margin_percent=MARGIN_PERCENT,
                denominations=_denoms(
                    game_code,
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
