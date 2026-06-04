"""Integration tests for analytics aggregation services."""

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
from yupay.modules.stats import service as svc
from yupay.modules.stats.schemas import AnalyticsRange

pytestmark = pytest.mark.asyncio


async def _seed_catalog(db: AsyncSession) -> tuple[str, str]:
    cat = Category(id=new_id(), slug="games", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug="pubg", category_id=cat.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name="PUBG")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug="pubg-uc", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="PUBG UC")]
    db.add(product)
    await db.flush()
    sku_with = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-60",
        price_usd=Decimal("1.00"),
        cost_usdt=Decimal("0.60"),
    )
    sku_no = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-300",
        price_usd=Decimal("5.00"),
        cost_usdt=None,
    )
    db.add_all([sku_with, sku_no])
    await db.flush()
    return sku_with.id, sku_no.id


async def _paid_order(
    db: AsyncSession, *, sku_id: str, qty: int, unit: str, paid_ago_days: int
) -> None:
    moment = now() - timedelta(days=paid_ago_days)
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status="delivered",
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


async def test_business_summary_and_margin_approx(db_session: AsyncSession) -> None:
    sku_with, sku_no = await _seed_catalog(db_session)
    # 2 units of the cost-known SKU @1.00 (cost 0.60) + 1 unit of cost-unknown @5.00
    await _paid_order(db_session, sku_id=sku_with, qty=2, unit="1.00", paid_ago_days=1)
    await _paid_order(db_session, sku_id=sku_no, qty=1, unit="5.00", paid_ago_days=2)

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    assert out.summary.orders == 2
    assert out.summary.gmv_usd == Decimal("7.00")  # 2.00 + 5.00
    # margin only over cost-known revenue: revenue 2.00, cost 1.20 → margin 0.80
    assert out.summary.gross_margin_usd == Decimal("0.80")
    assert out.summary.margin_approx is True
    assert out.summary.margin_unknown_units == 1
    # AOV = gmv / paid orders
    assert out.summary.aov_usd == Decimal("3.50")
    brands = {b.slug: b for b in out.top_brands}
    assert brands["pubg"].units == 3


async def test_range_filtering(db_session: AsyncSession) -> None:
    sku_with, _ = await _seed_catalog(db_session)
    await _paid_order(db_session, sku_id=sku_with, qty=1, unit="1.00", paid_ago_days=2)
    await _paid_order(db_session, sku_id=sku_with, qty=1, unit="1.00", paid_ago_days=40)
    out7 = await svc.build_business_analytics(db_session, r=AnalyticsRange.D7)
    out90 = await svc.build_business_analytics(db_session, r=AnalyticsRange.D90)
    assert out7.summary.orders == 1
    assert out90.summary.orders == 2
