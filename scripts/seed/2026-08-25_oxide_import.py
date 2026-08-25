"""Onboard Oxide: Survival Island into the catalog from G2B.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker compose exec -T api python - < scripts/seed/2026-08-25_oxide_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-25_oxide_import.py

Then apply the SEO pack: ``scripts/seed/oxide_seo.sql``.

Oxide: Survival Island is HYPERHUG's Rust-like mobile survival game — open
world, crafting, base building and raids. Coins are its premium currency:
blueprints, crafting resources, cupboard upkeep and skins.

**We sell the WEB BONUS ladder, not the plain one.** G2B lists both at the same
wholesale price, and the bonus tier gives strictly more coins at every rung —
verified against ``GET /games/oxide/catalogue`` on 2026-08-25:

    $2.346    50 Coins            vs  50 + 5 WEB BONUS      (55)
    $5.743    135 Coins           vs  125 + 20 WEB BONUS    (145)
    $11.434   290 Coins (15%)     vs  250 + 65 WEB BONUS    (315)
    $22.787   630 Coins (25%)     vs  500 + 175 WEB BONUS   (675)
    $56.855   1675 Coins (30%)    vs  1250 + 500 WEB BONUS  (1750)
    $113.638  3550 Coins (40%)    vs  2500 + 1250 WEB BONUS (3750)
    $340.782  —                       7500 + 3750 WEB BONUS (11250)

Selling the plain tier would charge the customer the same for less. The
competitor this was benchmarked against sells the bonus ladder too.

**No player-id check on the form, deliberately.** G2B's ``checkPlayerId``
rubber-stamps this game: every input of six characters or more comes back
``{"valid": "valid"}`` with ``nickname`` echoing the input rather than a real
player name, and it mints an Xsolla token for whatever id it was handed
(probed 2026-08-25 with ``999999999999``, ``0000000000``, ``ABCDEFGH``,
``abc123`` — all "valid"). Wiring that up would show the buyer their own typing
back under the word "проверено", which is worse than no check at all. Genshin
and Honkai: Star Rail are omitted for the same reason.

That makes the help text the only safeguard, so it carries the weight: copy the
id, do not retype it. Coins go to whatever id we are given and are not
reversible.

**The id is not digits-only.** The same probe accepted ``6Z-GJ4-03`` and
``AB-CD-12``, and the Xsolla payload behind the game carries a
``server_custom_id`` of exactly that shape — so a numeric pattern would reject
real customers at the one step where nothing else can catch a mistake.

**What is left out, and why.** The catalogue has 37 entries; we import 7.

* *Tickets* — five entries (5 / 10 / 25 / 50 / 100 Tickets) all priced at
  $1.224. Either that is an upstream data error or the tiers are not what their
  names say; selling them would mean charging one price for a twentyfold range.
* *X3 Coins …* — event bundles whose name does not say what arrives.
* *BP Coins*, *PREMIUM*, *5 Years Pass*, *Starter Pack 2*, *Epic Box*,
  *SPECIAL OFFER* — names a customer cannot map to anything in the game, which
  is a support ticket rather than a sale.
* *Weekly / Monthly Membership* — legible, and a reasonable second product
  later; kept out of the first import so the brand launches with one coherent
  ladder.

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

BRAND_SLUG = "oxide-survival-island"
GAME_CODE = "oxide"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------

_PLAYER_ID_HELP = {
    "ru": (
        "Откройте Oxide: Survival Island и нажмите на профиль на главном экране — "
        "User ID показан под иконкой профиля.\n"
        "Второй путь: «Параметры» (Settings) → там же указан User ID.\n"
        "Скопируйте его кнопкой копирования и вставьте — не набирайте вручную. "
        "Монеты уходят на тот ID, который получен, и вернуть их нельзя.\n"
        "Пароль и вход в аккаунт не нужны — пополнение идёт по публичному ID."
    ),
    "en": (
        "Open Oxide: Survival Island and tap your profile on the main screen — "
        "the User ID is shown under the profile icon.\n"
        "It is also in Settings, on the same screen.\n"
        "Copy it with the copy button and paste it — do not retype it. Coins go "
        "to whatever id we are given and cannot be taken back.\n"
        "No password or account login needed — top-up is by public ID."
    ),
    "uz": (
        "Oxide: Survival Island ni oching va bosh ekranda profilni bosing — "
        "User ID profil belgisi ostida koʻrsatiladi.\n"
        "Ikkinchi yoʻl: «Settings» — User ID oʻsha yerda.\n"
        "Nusxa olish tugmasi bilan koʻchiring va joylashtiring, qoʻlda termang. "
        "Tangalar qaysi ID berilsa, oʻshanga tushadi va qaytarib boʻlmaydi.\n"
        "Parol va akkauntga kirish kerak emas — toʻldirish ommaviy ID orqali."
    ),
}


def _required_fields() -> list[dict[str, Any]]:
    """One field, and no ``check``.

    The pattern is deliberately permissive: G2B accepted ``6Z-GJ4-03`` and
    ``AB-CD-12`` alongside plain digits, so anything narrower would turn a valid
    id into a refused sale. Length is the only bound worth enforcing here — it
    is also the only thing G2B itself checks.
    """
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "User ID", "en": "User ID", "uz": "User ID"},
            "required": True,
            "pattern": "^[A-Za-z0-9-]{4,32}$",
            "placeholder": {"ru": "6Z-GJ4-03", "en": "6Z-GJ4-03", "uz": "6Z-GJ4-03"},
            "help_text": _PLAYER_ID_HELP,
        },
    ]


# --- denominations ---------------------------------------------------------
#
# ``catalogue_name`` must match G2B's catalogue entry byte for byte —
# ``GET /games/oxide/catalogue``, read 2026-08-25. ``cost_usdt`` is what G2B
# quoted that day; the hourly refresh-all-prices job owns it afterwards.
# Cheapest first — ``import_game`` takes ``sort_order`` from this position.
#
# The label says the total the player receives (base + bonus), because that is
# the number they compare against every other shop. The split is kept in the
# name so the catalogue entry stays recognisable.

COIN_DENOMS: list[tuple[str, str, str]] = [
    ("50 + 5 WEB BONUS", "55 Coins (50 + 5)", "2.346"),
    ("125 + 20 WEB BONUS", "145 Coins (125 + 20)", "5.743"),
    ("250 + 65 WEB BONUS", "315 Coins (250 + 65)", "11.434"),
    ("500 + 175 WEB BONUS", "675 Coins (500 + 175)", "22.787"),
    ("1250 + 500 WEB BONUS", "1750 Coins (1250 + 500)", "56.855"),
    ("2500 + 1250 WEB BONUS", "3750 Coins (2500 + 1250)", "113.638"),
    ("7500 + 3750 WEB BONUS", "11250 Coins (7500 + 3750)", "340.782"),
]


def _sku_code(catalogue_name: str) -> str:
    """``oxide-50-5``, ``oxide-7500-3750``.

    Built from the digits in the catalogue name so a tier added above cannot
    silently collide with an existing code — ``Sku.sku_code`` is globally
    unique and a collision is reported as a skip, which would read as a
    successful import that quietly did less.
    """
    parts = [p for p in catalogue_name.split() if p.isdigit()]
    return "oxide-" + "-".join(parts)


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
    {"slug": "oxide-coins", "name": "Монеты", "denoms": COIN_DENOMS},
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
    """Give the denominations a price ladder. Idempotent."""
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
                        name="Oxide: Survival Island",
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
