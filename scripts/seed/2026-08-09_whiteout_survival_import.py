"""Onboard Whiteout Survival into the catalog from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-09_whiteout_survival_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-09_whiteout_survival_import.py

The simplest onboarding so far: G2B lists one product, ``whiteout_survival``
("Available for all users"), with one field — ``userid`` — and ten clean
denominations. No region split, no event bundles to filter, nothing for a
customer to get wrong beyond the id itself.

**A pricing note worth reading before this ships.** Century Games sells Frost
Stars at a fixed 100 per US dollar, so the tiers below map exactly onto official
prices: 99 → $0.99, 999 → $9.99, 9999 → $99.99. G2B's wholesale sits 3–6%
*above* that official retail, which is the opposite of every other game we
carry — PUBG and Mobile Legends both come in under. At the house 20% margin the
storefront therefore lands ~25% over what the official store charges in USD.

That is a defensible price for a customer who cannot pay Century Games directly
(the whole point of the storefront) and it is inside the range we already run —
Genshin sits at +21% over official. But it is a business call, not a technical
one, and it is one constant away: change ``MARGIN_PERCENT`` and re-run against a
fresh brand, or edit the prices in the admin afterwards.

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

BRAND_SLUG = "whiteout-survival"
PRODUCT_SLUG = "whiteout-survival-frost-stars"
GAME_CODE = "whiteout_survival"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------
#
# One key, `player_id` — what the G2B fulfiller reads out of `fulfillment_data`.
# No server field, so `check` carries no `server_field`; verified against G2B,
# which answers a bad Whiteout id with `{"valid": "invalid"}` rather than
# erroring, so the field can opt into the storefront verification.

_PLAYER_ID_HELP = {
    "ru": (
        "Откройте Whiteout Survival и нажмите на аватар в левом верхнем углу.\n"
        "Player ID показан в профиле под именем — рядом с ним есть кнопка "
        "копирования.\n"
        "Копируйте номер кнопкой, а не вручную: ID состоит только из цифр, "
        "а одна ошибка отправит покупку чужому игроку.\n"
        "Пароль не нужен — пополнение идёт по публичному ID."
    ),
    "en": (
        "Open Whiteout Survival and tap your avatar in the top-left corner.\n"
        "The Player ID is shown in the profile under your name, with a copy button "
        "next to it.\n"
        "Use the copy button rather than retyping: the ID is digits only, and one "
        "wrong digit sends the purchase to a stranger.\n"
        "No password needed — top-up is by public ID."
    ),
    "uz": (
        "Whiteout Survival ni oching va chap yuqori burchakdagi avatarni bosing.\n"
        "Player ID profilda ism ostida koʻrsatiladi, yonida nusxa olish tugmasi "
        "bor.\n"
        "Raqamni qoʻlda termay, tugma bilan koʻchiring: ID faqat raqamlardan "
        "iborat va bitta xato xaridni begona oʻyinchiga yuboradi.\n"
        "Parol kerak emas — toʻldirish ommaviy ID orqali."
    ),
}


def _required_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "Player ID", "en": "Player ID", "uz": "Player ID"},
            "required": True,
            "pattern": "^[0-9]{5,20}$",
            "placeholder": {"ru": "123456789", "en": "123456789", "uz": "123456789"},
            "help_text": _PLAYER_ID_HELP,
            "check": {"provider": "g2b"},
        },
    ]


# --- denominations ---------------------------------------------------------
#
# All ten G2B lists, cheapest first — `import_game` takes sort_order from this
# position. `catalogue_name` must match G2B's entry byte for byte. `cost_usdt` is
# what G2B quoted on 2026-08-09; the hourly refresh-all-prices job owns it after
# that. The trailing comment is the official USD price the tier corresponds to,
# at Century Games' fixed 100 Frost Stars per dollar.

DENOMS: list[tuple[str, str, str]] = [
    ("99", "99 Frost Stars", "1.04"),  # official $0.99
    ("299", "299 Frost Stars", "3.111"),  # $2.99
    ("499", "499 Frost Stars", "5.141"),  # $4.99
    ("999", "999 Frost Stars", "10.547"),  # $9.99
    ("1999", "1999 Frost Stars", "21.206"),  # $19.99
    ("4999", "4999 Frost Stars", "52.52"),  # $49.99
    ("7499", "7499 Frost Stars", "79.519"),  # $74.99
    ("9999", "9999 Frost Stars", "106.049"),  # $99.99
    ("18495", "18495 Frost Stars", "196.177"),  # $184.95
    ("29999", "29999 Frost Stars", "309.407"),  # $299.99
]


def _denoms() -> list[DenomImportIn]:
    return [
        DenomImportIn(
            catalogue_name=name,
            denomination=label,
            sku_code=f"wos-{name}",
            cost_usdt=Decimal(cost),
        )
        for name, label, cost in DENOMS
    ]


async def _games_category_id(session: Any) -> str:
    row = (await session.execute(select(Category).where(Category.slug == "games"))).scalar_one()
    return str(row.id)


async def _order_skus_by_price(session: Any, product_id: str) -> int:
    """Give the denominations a price ladder.

    Redundant against a current API — ``import_game`` now assigns ``sort_order``
    from the request position, and the list above is already cheapest-first. It
    stays because this script has to run against an API container that has not
    been redeployed yet, where every imported SKU still lands on the column
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
        existing_product = (
            await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
        ).scalar_one_or_none()
        if existing_product is not None:
            print(f"{PRODUCT_SLUG}: already exists ({existing_product.id}) — skipping import")
            ordered = await _order_skus_by_price(session, str(existing_product.id))
            await session.commit()
            print(f"ordered={ordered}\ncommitted")
            return

        brand = (
            await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
        ).scalar_one_or_none()
        brand_id = None if brand is None else str(brand.id)
        print(f"brand {BRAND_SLUG}: {'reusing ' + brand_id if brand_id else 'creating'}")

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
                    name="Whiteout Survival",
                )
            ),
            product=ProductImportIn(
                slug=PRODUCT_SLUG,
                name="Frost Stars",
                required_fields=_required_fields(),  # type: ignore[arg-type]
            ),
            margin_percent=MARGIN_PERCENT,
            denominations=_denoms(),
        )
        result = await import_game(session, payload, admin_id=ADMIN_ID)
        ordered = await _order_skus_by_price(session, result.product_id)
        print(
            f"  {PRODUCT_SLUG}: brand={result.brand_id} product={result.product_id} "
            f"skus={result.created_skus} mappings={result.created_mappings} "
            f"skipped={result.skipped} ordered={ordered}"
        )
        await session.commit()
        print("committed")


asyncio.run(main())
