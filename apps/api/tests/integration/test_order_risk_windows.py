"""Integration tests for the rolling-sum/velocity window rules (ADR-0047, Task 3).

Runs against real Postgres because the point being proven here is `_gather`'s
SQL — that an `OrderEvidence` IP correctly links otherwise-unrelated guest
orders into one identity — not the comparison logic in `_window_reason`,
which is fully covered (with fixed inputs, no database) by
`tests/unit/test_order_risk.py`.
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
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.risk import REASON_GEO_MISMATCH, REASON_ROLLING_SUM, review_reason
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _paid_guest_order(
    db: AsyncSession,
    *,
    guest_email: str,
    total_usd: str,
    paid_at_minutes_ago: int,
    ip: str,
) -> Order:
    """A minimal paid catalog order with an evidence row carrying its IP.

    No SKUs or order items: `_gather`'s Query A only joins `Order` and
    `OrderEvidence`, and its Query B (fulfilment-data targets) tolerates an
    order with no items — it simply contributes an empty target set.
    """
    moment = now()
    order = Order(
        id=new_id(),
        guest_email=guest_email,
        status="paid",
        currency="USD",
        total_usd=Decimal(total_usd),
        total_charged=Decimal(total_usd),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment - timedelta(minutes=paid_at_minutes_ago),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderEvidence(
            order_id=order.id,
            ip=ip,
            purge_after=moment + timedelta(days=180),
        )
    )
    await db.flush()
    return order


async def test_three_orders_sharing_one_ip_cross_the_rolling_sum_cap(
    db_session: AsyncSession,
) -> None:
    """Nothing but the IP links these three guests; $33 clears the $25 default cap."""
    shared_ip = "203.0.113.50"
    await _paid_guest_order(
        db_session,
        guest_email="a@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip=shared_ip,
    )
    await _paid_guest_order(
        db_session,
        guest_email="b@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip=shared_ip,
    )
    current = await _paid_guest_order(
        db_session,
        guest_email="c@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip=shared_ip,
    )
    await db_session.commit()

    assert await review_reason(db_session, current) == REASON_ROLLING_SUM


async def test_a_control_order_on_a_different_ip_and_buyer_is_untouched(
    db_session: AsyncSession,
) -> None:
    """The same shared-IP pair exists, but the order under test shares nothing with it."""
    shared_ip = "203.0.113.51"
    await _paid_guest_order(
        db_session,
        guest_email="d@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip=shared_ip,
    )
    await _paid_guest_order(
        db_session,
        guest_email="e@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip=shared_ip,
    )
    control = await _paid_guest_order(
        db_session,
        guest_email="control@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="198.51.100.99",
    )
    await db_session.commit()

    assert await review_reason(db_session, control) is None


# ---------- geo mismatch (rule 5) ----------


@pytest.fixture
async def _liquid_sku(db_session: AsyncSession) -> str:
    """A SKU under brand slug ``roblox`` — in the default `risk_liquid_brands`.

    Real catalog rows, not a stub: the point of this integration test is
    `_gather`'s brand join (order_items -> skus -> products -> brands), which
    a `WindowOrder`-only unit test cannot exercise.
    """
    category = Category(
        id=new_id(),
        slug="risk-geo-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Geo")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="roblox",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Roblox")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="risk-geo-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Geo Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="GEO-1",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("5.00"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _paid_order_with_item(
    db: AsyncSession,
    *,
    sku_id: str,
    user_id: str | None,
    guest_email: str | None,
    timezone: str | None,
) -> Order:
    """A paid catalog order for one liquid-brand SKU, with an evidence row
    reporting `timezone` (or none, when `timezone` is ``None``)."""
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        guest_email=guest_email,
        status="paid",
        currency="USD",
        total_usd=Decimal("5"),
        total_charged=Decimal("5"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("5"),
        )
    )
    db.add(
        OrderEvidence(
            order_id=order.id,
            client_hints={"timezone": timezone} if timezone else {},
            purge_after=moment + timedelta(days=180),
        )
    )
    await db.flush()
    await db.commit()
    return order


async def test_a_guest_liquid_brand_foreign_tz_order_is_held(
    db_session: AsyncSession, _liquid_sku: str
) -> None:
    order = await _paid_order_with_item(
        db_session,
        sku_id=_liquid_sku,
        user_id=None,
        guest_email="geo@example.test",
        timezone="Europe/Kiev",
    )

    assert await review_reason(db_session, order) == REASON_GEO_MISMATCH


async def test_the_same_order_signed_in_is_fulfilled(
    db_session: AsyncSession, _liquid_sku: str
) -> None:
    """Same brand, same foreign timezone — only ``user_id`` differs."""
    user_id = new_id()
    db_session.add(User(id=user_id, email="signed-in@example.test"))
    await db_session.flush()
    order = await _paid_order_with_item(
        db_session,
        sku_id=_liquid_sku,
        user_id=user_id,
        guest_email=None,
        timezone="Europe/Kiev",
    )

    assert await review_reason(db_session, order) is None
