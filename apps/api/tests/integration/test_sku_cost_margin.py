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
)

pytestmark = pytest.mark.asyncio


async def _seed_sku(
    db: AsyncSession,
    slug_suffix: str,
    *,
    cost_usdt: str,
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
        cost_usdt=Decimal(cost_usdt),
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


async def test_refuses_a_margin_that_would_zero_out_the_price(db_session: AsyncSession) -> None:
    """-99.99% is a legal margin (ck_skus_margin_percent_above_minus_100 only
    forbids <= -100), but on a $13 cost it rounds to a $0.00 price, which
    ck_skus_price_positive forbids. The write must skip price entirely (cost
    still updates) rather than crash the whole refresh tick on an
    IntegrityError."""
    sku_id = await _seed_sku(
        db_session, "zeroed", cost_usdt="10.00", price_usd="12.00", margin_percent="-99.99"
    )

    result = await catalog_svc.set_sku_cost_usdt(db_session, sku_id=sku_id, new_cost=Decimal("13"))
    await db_session.commit()

    assert result.new_price is None
    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13")
    assert sku.price_usd == Decimal("12.00")
