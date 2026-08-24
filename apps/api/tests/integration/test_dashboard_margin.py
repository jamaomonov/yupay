"""The margin the overview shows beside its revenue.

The two figures sit on one card, so the thing that can actually go wrong is
not the arithmetic — it is scope. A margin computed over a slightly different
window, or over deposits the revenue excludes, invites a comparison that does
not hold and is worse than showing nothing.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.stats.service import build_dashboard

pytestmark = pytest.mark.asyncio


async def _seed_skus(db: AsyncSession) -> tuple[str, str]:
    """One fixed SKU with a known cost, one without. Returns ``(known, unknown)``."""
    cat = Category(id=new_id(), slug=f"c-{new_id()[:8]}", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()
    brand = Brand(
        id=new_id(), slug=f"b-{new_id()[:8]}", category_id=cat.id, sort_order=0, active=True
    )
    brand.translations = [BrandTranslation(locale="ru", name="B")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug=f"p-{new_id()[:8]}", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="P")]
    db.add(product)
    await db.flush()
    known = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"k-{new_id()[:8]}",
        price_usd=Decimal("10.00"),
        cost_usdt=Decimal("8.00"),
    )
    unknown = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"u-{new_id()[:8]}",
        price_usd=Decimal("5.00"),
        cost_usdt=None,
    )
    db.add_all([known, unknown])
    await db.flush()
    return known.id, unknown.id


async def _order(
    db: AsyncSession,
    *,
    sku_id: str,
    qty: int,
    unit: str,
    status: str = "delivered",
    created_ago: timedelta = timedelta(hours=1),
) -> None:
    moment = now() - created_ago
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status=status,
        currency="USD",
        total_usd=Decimal(unit) * qty,
        total_charged=Decimal(unit) * qty,
        created_at=moment,
        paid_at=moment,
        delivered_at=moment,
        expires_at=moment + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=qty,
            unit_price_usd=Decimal(unit),
        )
    )
    await db.flush()


async def test_margin_is_gross_minus_cost(db_session: AsyncSession) -> None:
    known, _ = await _seed_skus(db_session)
    before = await build_dashboard(db_session, window_hours=24)

    # 3 units at 10.00 retail, 8.00 cost -> gross 30.00, margin 6.00, 20%.
    await _order(db_session, sku_id=known, qty=3, unit="10.00")

    after = await build_dashboard(db_session, window_hours=24)
    gained = after.margin_in_window.amount_usd - before.margin_in_window.amount_usd
    assert gained == Decimal("6.00")
    assert after.margin_in_window.unknown_units == before.margin_in_window.unknown_units


async def test_an_uncosted_sale_is_declared_not_counted_as_pure_margin(
    db_session: AsyncSession,
) -> None:
    """A SKU with no recorded cost must not read as 100% margin.

    Valuing an unknown cost at zero is the tempting shortcut, and it inflates
    the headline exactly on the products nobody has priced yet.
    """
    _, unknown = await _seed_skus(db_session)
    before = await build_dashboard(db_session, window_hours=24)

    await _order(db_session, sku_id=unknown, qty=4, unit="5.00")

    after = await build_dashboard(db_session, window_hours=24)
    assert after.margin_in_window.amount_usd == before.margin_in_window.amount_usd
    assert after.margin_in_window.unknown_units == before.margin_in_window.unknown_units + 4


async def test_margin_covers_the_same_orders_as_the_revenue_beside_it(
    db_session: AsyncSession,
) -> None:
    """Scope, not arithmetic, is what makes two figures on one card disagree."""
    known, _ = await _seed_skus(db_session)
    before = await build_dashboard(db_session, window_hours=24)

    # Outside the window: older than 24h. Counted by neither.
    await _order(db_session, sku_id=known, qty=5, unit="10.00", created_ago=timedelta(days=3))
    # Inside the window but never paid. Counted by neither.
    await _order(db_session, sku_id=known, qty=7, unit="10.00", status="expired")

    after = await build_dashboard(db_session, window_hours=24)
    assert after.margin_in_window.amount_usd == before.margin_in_window.amount_usd
    assert after.margin_in_window.unknown_units == before.margin_in_window.unknown_units
