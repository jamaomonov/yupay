"""Onboard Blood Strike into the catalog from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-09_blood_strike_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-09_blood_strike_import.py

**No region split here.** Unlike the two Moonton games
([ADR-0048](../../docs/decisions/0048-mobile-legends-region-split.md)), G2B
lists Blood Strike twice with no region lock on either — live
``/games/{code}/fields`` notes, 2026-08-09:

    bloodstrike    "Available for all users"  — 30 denominations
    bloodstrikeme  "Available for all users"  — 30 denominations, ~18% dearer

``bloodstrikeme`` is branded MENA and prices every comparable item above
``bloodstrike`` (51 Gold: $0.469 vs $0.398). Both claim to serve everyone, so we
map the cheaper one and there is no choice for the customer to get wrong.

The form is one field. NetEase credits by UID alone — no server, no zone — so
the split that makes this brand legible is the house one, by what is being
bought: gold and passes, the way `free-fire-diamonds` sits beside
`free-fire-membership`.

The event and gacha entries are left out: `049deal`…`999deal` say nothing about
what arrives, and `Lucky Bag Week`, `Ultra Skin Lucky Chest` and the Attack on
Titan tie-ins are dated collaborations. A SKU that disappears upstream is a
failed order, and a name a customer cannot read is a support ticket.

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

BRAND_SLUG = "blood-strike"
GAME_CODE = "bloodstrike"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------
#
# One key, `player_id`, because that is what the G2B fulfiller reads out of
# `fulfillment_data`. No sibling server field, so `check` carries no
# `server_field` — verified against G2B: checkPlayerId answers a bad Blood
# Strike id with `{"valid": "invalid"}` rather than erroring, so the field can
# opt into the storefront verification.
#
# The copy-button instruction is not padding. NetEase credits whatever UID it is
# given and does not reverse it, so a single mistyped digit is gold delivered to
# a stranger — the one failure on this page we cannot undo.

_PLAYER_ID_HELP = {
    "ru": (
        "Откройте Blood Strike и нажмите на аватар в левом верхнем углу лобби — "
        "User ID показан в профиле.\n"
        "Надёжнее через настройки: «Settings» → «Account» → «User ID».\n"
        "Нажмите значок копирования рядом с номером, не набирайте вручную: "
        "ID состоит только из цифр, а одна ошибка отправит золото чужому игроку.\n"
        "Пароль не нужен — пополнение идёт по публичному ID."
    ),
    "en": (
        "Open Blood Strike and tap your avatar in the top-left corner of the lobby — "
        "the User ID is shown on the profile screen.\n"
        "The more reliable route is Settings → Account → User ID.\n"
        "Tap the copy icon next to the number instead of retyping it: the ID is "
        "digits only, and one wrong digit sends the gold to a stranger.\n"
        "No password needed — top-up is by public ID."
    ),
    "uz": (
        "Blood Strike ni oching va lobbi chap yuqori burchagidagi avatarni bosing — "
        "User ID profil ekranida koʻrsatiladi.\n"
        "Ishonchliroq yoʻl: «Settings» → «Account» → «User ID».\n"
        "Raqamni qoʻlda termang, yonidagi nusxa belgisini bosing: ID faqat "
        "raqamlardan iborat va bitta xato oltinni begona oʻyinchiga yuboradi.\n"
        "Parol kerak emas — toʻldirish ommaviy ID orqali."
    ),
}


def _required_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "User ID", "en": "User ID", "uz": "User ID"},
            "required": True,
            "pattern": "^[0-9]{5,20}$",
            "placeholder": {"ru": "123456789", "en": "123456789", "uz": "123456789"},
            "help_text": _PLAYER_ID_HELP,
            "check": {"provider": "g2b"},
        },
    ]


# --- denominations ---------------------------------------------------------
#
# `catalogue_name` must match G2B's catalogue entry byte for byte. `cost_usdt` is
# what G2B quoted on 2026-08-09; the hourly refresh-all-prices job owns it after
# that. Cheapest first — `import_game` takes sort_order from this position.

GOLD_DENOMS: list[tuple[str, str, str]] = [
    ("51", "51 Gold", "0.398"),
    ("105", "105 Gold", "0.755"),
    ("320", "320 Gold", "2.254"),
    ("540", "540 Gold", "3.743"),
    ("1100", "1100 Gold", "7.497"),
    ("2260", "2260 Gold", "14.974"),
    ("5800", "5800 Gold", "37.628"),
]

PASS_DENOMS: list[tuple[str, str, str]] = [
    ("Level Up Pass", "Level Up Pass", "1.561"),
    ("Strike Pass Elite", "Strike Pass Elite", "3.101"),
    ("Strike Pass Premium", "Strike Pass Premium", "6.987"),
]


def _sku_code(catalogue_name: str) -> str:
    """`bs-51`, `bs-strike-pass-elite`.

    Derived from the catalogue name rather than hand-written so a denomination
    added to the lists above cannot silently collide with an existing code —
    `Sku.sku_code` is globally unique and a collision is reported as a skip, not
    an error, which would read as a successful import that quietly did less.
    """
    return f"bs-{catalogue_name.lower().replace(' ', '-')}"


def _denoms(rows: list[tuple[str, str, str]]) -> list[DenomImportIn]:
    return [
        DenomImportIn(
            catalogue_name=name,
            denomination=label,
            sku_code=_sku_code(name),
            cost_usdt=Decimal(cost),
        )
        for name, label, cost in rows
    ]


PRODUCTS = [
    {"slug": "blood-strike-gold", "name": "Золото", "denoms": GOLD_DENOMS},
    {"slug": "blood-strike-passes", "name": "Пропуска", "denoms": PASS_DENOMS},
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
                game_code=GAME_CODE,
                target="new_brand" if brand_id is None else "existing_brand",
                brand_id=brand_id,
                new_brand=(
                    None
                    if brand_id is not None
                    else NewBrandIn(
                        slug=BRAND_SLUG,
                        category_id=category_id,
                        name="Blood Strike",
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
