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
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order
from yupay.modules.orders.risk import REASON_ROLLING_SUM, review_reason

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
