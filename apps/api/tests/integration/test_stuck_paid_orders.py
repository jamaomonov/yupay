"""``list_stuck_paid_orders`` against a real database (ADR-0046).

The query is the whole safeguard, so what matters is which orders it refuses to
miss — in particular one with no fulfillment task at all, which production had
and which a task-shaped query reports as all clear.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import list_stuck_paid_orders


async def _order(
    db: AsyncSession,
    *,
    status: str,
    paid_minutes_ago: int | None,
    delivered: bool = False,
    amount: str = "100000",
) -> str:
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=f"{new_id()[:8]}@example.com",
        status=status,
        currency="UZS",
        total_usd=Decimal("7.25"),
        total_charged=Decimal(amount),
        expires_at=now() + timedelta(hours=1),
        paid_at=(now() - timedelta(minutes=paid_minutes_ago)) if paid_minutes_ago else None,
        delivered_at=now() if delivered else None,
    )
    db.add(order)
    await db.commit()
    return order.id


async def test_catches_a_paid_order_with_no_fulfillment_task_at_all(
    db_session: AsyncSession,
) -> None:
    """The July-23 shape: money taken, nothing downstream ever created.

    A watchdog written over ``fulfillment_tasks`` would report all clear here,
    which is exactly how this order went unnoticed for two weeks.
    """
    stuck = await _order(db_session, status="paid", paid_minutes_ago=90)

    found = await list_stuck_paid_orders(db_session, older_than_minutes=15)

    assert stuck in [o.id for o in found]


async def test_catches_a_failed_supplier_call(db_session: AsyncSession) -> None:
    """The 2026-08-07 shape: task created, supplier refused, order left
    ``fulfilling`` for the admin — per ADR-0040, which assumed the admin looks."""
    stuck = await _order(db_session, status="fulfilling", paid_minutes_ago=1_440)

    found = await list_stuck_paid_orders(db_session, older_than_minutes=15)

    assert stuck in [o.id for o in found]


async def test_ignores_orders_still_inside_the_normal_delivery_window(
    db_session: AsyncSession,
) -> None:
    """Delivery normally takes 1-5 minutes. Alerting at minute two would train
    the operator to ignore the channel, which is worse than not alerting."""
    fresh = await _order(db_session, status="fulfilling", paid_minutes_ago=3)

    found = await list_stuck_paid_orders(db_session, older_than_minutes=15)

    assert fresh not in [o.id for o in found]


async def test_ignores_delivered_expired_and_unpaid_orders(db_session: AsyncSession) -> None:
    delivered = await _order(db_session, status="delivered", paid_minutes_ago=600, delivered=True)
    expired = await _order(db_session, status="expired", paid_minutes_ago=None)
    refunded = await _order(db_session, status="refunded", paid_minutes_ago=600)

    ids = [o.id for o in await list_stuck_paid_orders(db_session, older_than_minutes=15)]

    assert delivered not in ids
    assert expired not in ids
    # A refund is a resolution: the customer has their money back, so there is
    # nothing left for an operator to do and nothing to keep shouting about.
    assert refunded not in ids


async def test_oldest_first(db_session: AsyncSession) -> None:
    """Ordering is the triage: the longest-waiting customer is the closest to
    filing a dispute."""
    newer = await _order(db_session, status="fulfilling", paid_minutes_ago=30)
    older = await _order(db_session, status="fulfilling", paid_minutes_ago=900)

    found = [o.id for o in await list_stuck_paid_orders(db_session, older_than_minutes=15)]

    assert found.index(older) < found.index(newer)
