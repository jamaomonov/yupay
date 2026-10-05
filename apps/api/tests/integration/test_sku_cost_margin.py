"""``catalog.admin_service.set_sku_cost_usdt`` — the margin-aware half.

The supplier price-refresh pipeline is covered end-to-end (G2B mock →
Telegram alert) in ``test_integrations_price_refresh.py``. This file tests
``set_sku_cost_usdt`` directly, without the G2B/HTTP layer, for the
branches that pipeline doesn't exercise: a no-op cost (nothing to
re-derive from) and a pathological margin that would drive price_usd to
zero or below.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog import admin_service as catalog_svc
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
    SkuPrice,
)

pytestmark = pytest.mark.asyncio


async def _seed_sku(
    db: AsyncSession,
    slug_suffix: str,
    *,
    cost_usdt: str | None,
    price_usd: str,
    margin_percent: str | None,
) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{slug_suffix}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"br-{slug_suffix}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Br")],
    )
    product = Product(
        id=new_id(),
        slug=f"prod-{slug_suffix}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{slug_suffix}",
        denomination="60",
        region="WW",
        price_usd=Decimal(price_usd),
        cost_usdt=Decimal(cost_usdt) if cost_usdt else None,
        margin_percent=Decimal(margin_percent) if margin_percent else None,
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def test_recomputes_price_when_margin_is_saved_and_cost_moves(
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(
        db_session, "moves", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )

    result = await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("13"))
    await db_session.commit()

    assert result.previous_cost == Decimal("10.000000")
    assert result.previous_price == Decimal("12.000000")
    assert result.new_price == Decimal("15.60")
    assert result.margin_percent == Decimal("20.0000")

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13")
    assert sku.price_usd == Decimal("15.60")


async def test_leaves_price_untouched_when_the_cost_does_not_move(
    db_session: AsyncSession,
) -> None:
    """Even with a margin on file, re-sending the *same* cost must not
    perturb price_usd — there's nothing new to protect against."""
    sku_id = await _seed_sku(
        db_session, "noop", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("10.00")
    )
    await db_session.commit()

    assert result.new_price is None
    assert result.previous_price is None
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.price_usd == Decimal("12.00")


async def test_leaves_price_untouched_without_a_saved_margin(db_session: AsyncSession) -> None:
    sku_id = await _seed_sku(
        db_session, "no-margin", cost_usdt="10.00", price_usd="12.00", margin_percent=None
    )

    result = await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("13"))
    await db_session.commit()

    assert result.new_price is None
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13")
    assert sku.price_usd == Decimal("12.00")


# ---------- allow_price_drop — the ratchet (§5 of the sourcing-by-brand design) ----------


async def test_default_still_lowers_price_on_a_cost_drop(db_session: AsyncSession) -> None:
    """The flag must default to today's behaviour: every existing caller
    that doesn't pass ``allow_price_drop`` keeps lowering the price on a
    cost drop, exactly as before the flag existed. Called with no keyword
    at all, on purpose — a default that silently flipped would be the bug
    this whole feature exists to prevent."""
    sku_id = await _seed_sku(
        db_session, "default-drop", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )

    result = await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("8"))
    await db_session.commit()

    assert result.price_drop_blocked is False
    assert result.new_price == Decimal("9.60")
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("8")
    assert sku.price_usd == Decimal("9.60")


async def test_allow_price_drop_true_lowers_price_on_a_cost_drop(
    db_session: AsyncSession,
) -> None:
    """Explicit ``True`` (the operator/mapping-save path): a cost drop still
    lowers the price, exactly like the default."""
    sku_id = await _seed_sku(
        db_session, "explicit-true-drop", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("8"), allow_price_drop=True
    )
    await db_session.commit()

    assert result.price_drop_blocked is False
    assert result.new_price == Decimal("9.60")
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("8")
    assert sku.price_usd == Decimal("9.60")


async def test_allow_price_drop_false_leaves_price_byte_identical_on_a_cost_drop(
    db_session: AsyncSession,
) -> None:
    """The hourly/automatic path: a cost drop updates ``cost_usdt`` (the
    margin report should tell the truth) but must not touch ``price_usd``
    at all — asserted byte-identical against the Decimal the SKU was
    seeded with, not merely "not the new candidate"."""
    sku_id = await _seed_sku(
        db_session, "false-drop", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )
    seeded_price = (
        await db_session.execute(select(Sku.price_usd).where(Sku.id == sku_id))
    ).scalar_one()

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("8"), allow_price_drop=False
    )
    await db_session.commit()

    assert result.new_price is None
    assert result.previous_price is None
    assert result.margin_percent is None
    assert result.price_drop_blocked is True

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("8"), "cost must still move — the margin report must widen"
    assert sku.price_usd == seeded_price
    assert sku.price_usd == Decimal("12.00")


async def test_a_rise_still_raises_the_price_with_allow_price_drop_false(
    db_session: AsyncSession,
) -> None:
    """The half that protects the margin against a supplier price
    increase must survive the flag: a rise raises the price under
    ``allow_price_drop=False`` exactly as it does under ``True``."""
    sku_id = await _seed_sku(
        db_session, "false-rise", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("13"), allow_price_drop=False
    )
    await db_session.commit()

    assert result.price_drop_blocked is False
    assert result.new_price == Decimal("15.60")
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13")
    assert sku.price_usd == Decimal("15.60")


async def test_a_rise_still_raises_the_price_with_allow_price_drop_true(
    db_session: AsyncSession,
) -> None:
    """Same rise, opposite flag — the two flag values must agree on a
    rise; only a drop is where they're allowed to diverge."""
    sku_id = await _seed_sku(
        db_session, "true-rise", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("13"), allow_price_drop=True
    )
    await db_session.commit()

    assert result.price_drop_blocked is False
    assert result.new_price == Decimal("15.60")
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13")
    assert sku.price_usd == Decimal("15.60")


async def test_no_margin_untouched_by_a_drop_regardless_of_the_flag(
    db_session: AsyncSession,
) -> None:
    """A SKU with no saved margin has nothing for the ratchet to protect —
    same "cost updates, price alone" outcome whichever way the flag is
    set, on a drop this time (the existing no-margin test only covers a
    rise)."""
    for suffix, allow in (("no-margin-drop-false", False), ("no-margin-drop-true", True)):
        sku_id = await _seed_sku(
            db_session, suffix, cost_usdt="10.00", price_usd="12.00", margin_percent=None
        )

        result = await catalog_svc.set_sku_cost_usdt(
            db_session, sku_id=sku_id, new_cost=Decimal("8"), allow_price_drop=allow
        )
        await db_session.commit()

        assert result.new_price is None
        assert result.price_drop_blocked is False
        sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
        assert sku.cost_usdt == Decimal("8")
        assert sku.price_usd == Decimal("12.00")


async def test_a_margin_that_would_zero_out_the_price_lands_on_one_cent(
    db_session: AsyncSession,
) -> None:
    """-99.99% is a legal margin (ck_skus_margin_percent_above_minus_100 only
    forbids <= -100); on a $13 cost it comes to $0.0013. Half-up made that
    $0.00, which ck_skus_price_positive forbids, so the write used to skip the
    price. Rounding up (2026-10-05) makes it $0.01 — the smallest sellable
    price — and the ``candidate > 0`` guard stays as a belt for a rounding
    that can no longer reach zero on a positive cost."""
    sku_id = await _seed_sku(
        db_session, "zeroed", cost_usdt="10.00", price_usd="12.00", margin_percent="-99.99"
    )

    result = await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("13"))
    await db_session.commit()

    assert result.new_price == Decimal("0.01")
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13")
    assert sku.price_usd == Decimal("0.01")


async def test_a_sub_dime_sku_keeps_its_margin_by_rounding_up(db_session: AsyncSession) -> None:
    """Amazon EG on prod: cost $0.0192 at 13% is $0.0217. Half-up sold it at
    $0.02 — a 4% margin; up sells it at $0.03."""
    sku_id = await _seed_sku(
        db_session, "subdime", cost_usdt="0.0190", price_usd="0.02", margin_percent="13"
    )

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("0.0192"), allow_price_drop=False
    )
    await db_session.commit()

    assert result.new_price == Decimal("0.03")


async def test_a_rise_parked_under_the_price_is_not_reported_as_a_blocked_drop(
    db_session: AsyncSession,
) -> None:
    """The sentence this flag selects has to match what happened.

    A price parked above its margin — which is what this whole design
    accumulates — means a cost **rise** can still produce a candidate at or
    below it. The assignment correctly leaves the price alone, but calling that
    a blocked *drop* prints "наценка выросла" directly under "себестоимость
    выросла", which is the one alert the rise-half exists to make legible.
    """
    sku_id = await _seed_sku(
        db_session,
        slug_suffix="rise-under-park",
        cost_usdt="0.79",
        price_usd="0.90",
        margin_percent="10",
    )

    # Cost rises 0.79 -> 0.81; candidate 0.89 is still under the parked 0.90.
    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("0.81"), allow_price_drop=False
    )
    await db_session.commit()

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.81"), "the cost still syncs"
    assert sku.price_usd == Decimal("0.90"), "and the price is still left alone"
    assert result.price_drop_blocked is False, "but nothing was being dropped"


async def test_a_first_ever_cost_is_not_a_blocked_drop(db_session: AsyncSession) -> None:
    """A SKU that never had a cost is not a SKU whose cost fell.

    The enclosing condition is `previous_cost != new_cost`, which is true when
    the previous cost is `None` — so this branch is reachable on the very first
    sync of a SKU, and comparing a Decimal to None there is a crash rather than
    a wrong answer.
    """
    sku_id = await _seed_sku(
        db_session, "first-cost", cost_usdt=None, price_usd="0.90", margin_percent="10"
    )

    result = await catalog_svc.set_sku_cost_usdt(
        db_session, sku_id=sku_id, new_cost=Decimal("0.79"), allow_price_drop=False
    )
    await db_session.commit()

    assert result.price_drop_blocked is False
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.79")


async def test_a_currency_override_moves_with_the_margin_derived_price(
    db_session: AsyncSession,
) -> None:
    """A UZS override is charged as-is at checkout, with no rate and no markup.
    Left at 12 000 while the SKU went from $12.00 to $15.60 it would sell under
    the margin; it keeps its ratio to the USD price instead."""
    sku_id = await _seed_sku(
        db_session, "override", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )
    db_session.add(SkuPrice(sku_id=sku_id, currency="UZS", price=Decimal("152400")))
    db_session.add(SkuPrice(sku_id=sku_id, currency="RUB", price=Decimal("1000.00")))
    await db_session.commit()

    result = await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("13"))
    await db_session.commit()
    assert result.new_price == Decimal("15.60")

    rows = {
        o.currency: o.price
        for o in (
            await db_session.execute(select(SkuPrice).where(SkuPrice.sku_id == sku_id))
        ).scalars()
    }
    assert rows["UZS"] == Decimal("198120")  # 152 400 × 15.60 / 12.00, whole soʻm
    assert rows["RUB"] == Decimal("1300.00")
