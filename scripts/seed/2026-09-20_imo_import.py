"""Import the IMO brand — diamonds, from G2B *and* NOVA.

Run inside the api container (it needs the ``yupay`` package and the DB):

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-09-20_imo_import.py

Then its copy, which UPDATEs rows this creates:

    docker exec -i yupay-prod-postgres-1 sh -lc \
      'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
      < scripts/seed/imo_seo.sql

IMO is a messenger; diamonds are its in-app currency, spent on gifts in live
streams and bought against a public numeric IMO ID. That shape — an app's own
currency, topped up by id, no game server — is Telegram Stars', which is why
the brand lands in ``subscriptions`` beside it rather than in ``games``.

## The two ladders do not overlap. Not one rung.

Read live from both suppliers on 2026-09-20:

    G2B  (games_catalogue 'imo'):  200, 500, 1000, 2000, 5000
    NOVA (get_offers 'imo'):       10, 100, 160, 210, 420, 840, 1680, 2100,
                                   4200, 8400, 16800, 21000

So there is **no SKU either supplier could take over from the other**. This is
not the usual "map a second supplier as a fallback" import: every one of the
seventeen rungs below has exactly one source, and a rung whose supplier goes
down is down. That is worth knowing before an outage rather than during one.

Per-diamond wholesale: G2B $0.01870, NOVA $0.01984 — G2B is ~6% cheaper, and
its rungs are the round numbers a customer recognises. NOVA's value is the
range G2B does not sell at all: the $0.21 entry point (10 diamonds) and
everything above 5000, up to 21000 for ~$417.

The union is monotonic in both amount and cost, so the shelf still reads as
one ascending ladder even though it is stitched from two catalogues.

## Why NOVA's twelve get an explicit sourcing rule

NOVA is a **reserve** supplier (``RESERVE_SUPPLIERS``, ADR-0081):
``sourcing._pick_auto_mapping_slug`` skips it whatever its mapping's age, so a
SKU whose only mapping is NOVA resolves to *no supplier at all* and every
order against it fails to route. Left alone, twelve of these seventeen SKUs
would be unsellable — listed, priced, and dead.

So each NOVA rung gets ``mode='force_supplier', supplier_slug='nova'``. That
is exactly the "explicit decision" ADR-0081 asks for, made in a reviewable
diff instead of twelve clicks; and the risk the ADR guards against — orders
drifting to a supplier nobody chose — cannot arise here, because these SKUs
have no other supplier to drift away from.

**The NOVA wallet must be funded before these twelve can sell.** They are
created active; if that is wrong, deactivate them in the admin.

## Not imported

* **G2B's IMO gift cards** (voucher ids 65 and 66, $1 and $5). A different
  product kind — a code from the voucher warehouse, not a top-up by id — and
  a different decision. Say so and they can follow.
* **Player validation.** NOVA publishes one required field (``imo_id``, text)
  and no validator for it; G2B answers ``404 game fields not available`` for
  this game. Neither was tested against a real IMO id, and a probe with an
  invented one proves nothing about whether validation works (ADR-0085). So
  no ``check`` is wired: an unverified field is better than a verification
  that verifies nothing. The help text carries the weight instead.

Margin 15%, which is where the catalogue sits (13–16% across every brand
with more than three SKUs). Costs below are the 2026-09-20 quotes; the hourly
price-refresh job owns them from then on.

Idempotent: existing ``sku_code``s are skipped, mappings and rules converge on
the same values, and the re-sort rewrites the ladder it already has.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
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
from yupay.modules.integrations.service import MappingUpsert, import_game, upsert_mapping
from yupay.modules.sourcing.service import set_rule

BRAND_SLUG = "imo"
CATEGORY_SLUG = "subscriptions"
PRODUCT_SLUG = "imo-diamonds"
G2B_GAME_CODE = "imo"
NOVA_CATEGORY_ID = "imo"
MARGIN_PERCENT = Decimal("15")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

# --- form schema -----------------------------------------------------------
#
# One key, `player_id`, because that is what both fulfillers read out of
# `fulfillment_data` — NOVA calls the field `imo_id` on its side, and the
# adapter maps it; the storefront key stays the one every other top-up uses.
#
# No `check`: see the module docstring. The copy-button instruction is not
# padding — IMO credits whatever id it is given and does not reverse it, so a
# mistyped digit is diamonds delivered to a stranger.

_PLAYER_ID_HELP = {
    "ru": (
        "Откройте imo и перейдите в «Профиль» — IMO ID показан под вашим именем.\n"
        "Нажмите на номер, чтобы скопировать его, и не набирайте вручную: ID "
        "состоит только из цифр, а одна ошибка отправит алмазы чужому человеку.\n"
        "Пароль и код из SMS не нужны — пополнение идёт по публичному ID."
    ),
    "en": (
        "Open imo and go to Profile — your IMO ID is shown under your name.\n"
        "Tap the number to copy it instead of retyping: the ID is digits only, "
        "and one wrong digit sends the diamonds to a stranger.\n"
        "No password and no SMS code needed — the top-up goes by public ID."
    ),
    "uz": (
        "imo ni oching va «Profil» boʻlimiga oʻting — IMO ID ismingiz ostida "
        "koʻrsatiladi.\n"
        "Raqamni qoʻlda termang, bosib nusxa oling: ID faqat raqamlardan iborat "
        "va bitta xato olmoslarni begona odamga yuboradi.\n"
        "Parol va SMS kod kerak emas — toʻldirish ommaviy ID orqali."
    ),
}


def _required_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "player_id",
            "type": "text",
            "label": {"ru": "IMO ID", "en": "IMO ID", "uz": "IMO ID"},
            "required": True,
            "pattern": "^[0-9]{6,20}$",
            "placeholder": {"ru": "123456789", "en": "123456789", "uz": "123456789"},
            "help_text": _PLAYER_ID_HELP,
        },
    ]


# --- denominations ---------------------------------------------------------
#
# (amount, supplier variant id, cost). For G2B the variant is the catalogue
# name, byte for byte; for NOVA it is the offer_id. Cheapest first — the sort
# order is the position in this list.

G2B_DENOMS: list[tuple[int, str, str]] = [
    (200, "200 Diamonds", "3.73"),
    (500, "500 Diamonds", "9.35"),
    (1000, "1000 Diamonds", "18.7"),
    (2000, "2000 Diamonds", "37.4"),
    (5000, "5000 Diamonds", "93.5"),
]

NOVA_DENOMS: list[tuple[int, str, str]] = [
    (10, "10_diamonds", "0.2142"),
    (100, "100_diamonds", "1.989"),
    (160, "160_diamonds", "3.1926"),
    (210, "210_diamonds", "4.182"),
    (420, "420_diamonds", "8.3436"),
    (840, "840_diamonds", "16.677"),
    (1680, "1680_diamonds", "33.3336"),
    (2100, "2100_diamonds", "41.6568"),
    (4200, "4200_diamonds", "83.3136"),
    (8400, "8400_diamonds", "166.6272"),
    (16800, "16800_diamonds", "333.2442"),
    (21000, "21000_diamonds", "416.5578"),
]


def _sku_code(amount: int) -> str:
    """``imo-200``. Derived from the amount so two sources cannot collide."""
    return f"imo-{amount}"


def _denomination(amount: int) -> str:
    return f"{amount} Diamonds"


def _sell_price(cost: Decimal) -> Decimal:
    """The same formula ``integrations.service._sell_price`` uses."""
    return (cost * (Decimal(1) + MARGIN_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _category_id(session: Any) -> str:
    row = (
        await session.execute(select(Category).where(Category.slug == CATEGORY_SLUG))
    ).scalar_one()
    return str(row.id)


async def _brand_id(session: Any) -> str | None:
    row = (
        await session.execute(select(Brand).where(Brand.slug == BRAND_SLUG))
    ).scalar_one_or_none()
    return None if row is None else str(row.id)


async def _product_id(session: Any, brand_id: str) -> str:
    row = (
        await session.execute(
            select(Product).where(Product.brand_id == brand_id, Product.slug == PRODUCT_SLUG)
        )
    ).scalar_one()
    return str(row.id)


async def _import_g2b(session: Any) -> tuple[str, str, int, list[str]]:
    """Brand + product + the five G2B rungs, through the ordinary importer."""
    payload = GameImportIn(
        game_code=G2B_GAME_CODE,
        target="new_brand",
        new_brand=NewBrandIn(
            slug=BRAND_SLUG,
            category_id=await _category_id(session),
            name="IMO",
        ),
        product=ProductImportIn(
            slug=PRODUCT_SLUG,
            name="Алмазы",
            required_fields=_required_fields(),  # type: ignore[arg-type]
        ),
        margin_percent=MARGIN_PERCENT,
        denominations=[
            DenomImportIn(
                catalogue_name=variant,
                denomination=_denomination(amount),
                sku_code=_sku_code(amount),
                cost_usdt=Decimal(cost),
            )
            for amount, variant, cost in G2B_DENOMS
        ],
    )
    existing = await _brand_id(session)
    if existing is not None:
        payload = payload.model_copy(update={"target": "existing_brand", "brand_id": existing})
    result = await import_game(session, payload, admin_id=ADMIN_ID)
    return result.brand_id, result.product_id, result.created_skus, result.skipped


async def _import_nova(session: Any, *, product_id: str) -> tuple[int, list[str]]:
    """The twelve NOVA rungs: SKU, mapping, and the rule that makes them sell."""
    from yupay.modules.catalog import admin_schemas as catalog_schemas
    from yupay.modules.catalog import admin_service as catalog

    codes = [_sku_code(a) for a, _, _ in NOVA_DENOMS]
    present = set(
        (await session.execute(select(Sku.sku_code).where(Sku.sku_code.in_(codes)))).scalars().all()
    )

    created = 0
    skipped: list[str] = []
    for position, (amount, offer_id, cost) in enumerate(NOVA_DENOMS):
        code = _sku_code(amount)
        if code in present:
            skipped.append(code)
            # Still converge the mapping and the rule: a re-run must be able to
            # repair a half-applied import, and a SKU that exists without its
            # rule is the unsellable state this script exists to avoid.
            sku_id = (
                await session.execute(select(Sku.id).where(Sku.sku_code == code))
            ).scalar_one()
        else:
            sku = await catalog.create_sku(
                session,
                catalog_schemas.SkuCreate(
                    product_id=product_id,
                    sku_code=code,
                    denomination=_denomination(amount),
                    price_usd=_sell_price(Decimal(cost)),
                    cost_usdt=Decimal(cost),
                    sort_order=len(G2B_DENOMS) + position,
                ),
            )
            sku_id = sku.id
            created += 1

        # Every field spelled out: `MappingUpsert` is a frozen dataclass with
        # no defaults, so an omission is a TypeError here rather than a silently
        # inactive mapping later.
        await upsert_mapping(
            session,
            MappingUpsert(
                sku_id=sku_id,
                supplier_slug="nova",
                kind="game",
                external_product_id=NOVA_CATEGORY_ID,
                external_variant_id=offer_id,
                quantity=1,
                extra={},
                is_active=True,
                updated_by=ADMIN_ID,
            ),
        )
        # Without this the SKU cannot be routed at all — see the docstring.
        await set_rule(
            session,
            sku_id=sku_id,
            mode="force_supplier",
            supplier_slug="nova",
            admin_id=ADMIN_ID,
        )
    return created, skipped


async def _order_by_price(session: Any, product_id: str) -> int:
    """Give the stitched ladder one ascending order."""
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
    factory = get_session_factory()
    async with factory() as session:
        brand_id, product_id, g2b_created, g2b_skipped = await _import_g2b(session)
        nova_created, nova_skipped = await _import_nova(session, product_id=product_id)
        ordered = await _order_by_price(session, product_id)
        await session.commit()

    print(f"brand   {BRAND_SLUG}  {brand_id}")
    print(f"product {PRODUCT_SLUG}  {product_id}")
    print(f"g2b     created {g2b_created}, skipped {len(g2b_skipped)} {g2b_skipped}")
    print(f"nova    created {nova_created}, skipped {len(nova_skipped)} {nova_skipped}")
    print(f"ladder  {ordered} SKUs ordered by price")
    print()
    print("NEXT: run scripts/seed/imo_seo.sql, upload the brand logo in the admin,")
    print("      and fund the NOVA wallet before the twelve NOVA rungs can sell.")


asyncio.run(main())
