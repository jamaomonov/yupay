"""Cascade-cancel pending payments when their order terminates.

When an order moves to ``expired`` or admin-``cancelled``, any pending /
requires_action payment intents for that order must close too — otherwise
they sit forever in /payments/triage and the operator wastes time chasing
ghosts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.orders import service as orders_svc
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment, PaymentAttempt
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _make_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id[:8]}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()
    return user_id


async def _make_order(
    db: AsyncSession,
    *,
    user_id: str,
    status: str = "pending_payment",
    expires_in_minutes: int = 10,
) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status=status,
            currency="USD",
            total_usd=Decimal("10.00"),
            total_charged=Decimal("10.00"),
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        )
    )
    await db.flush()
    return order_id


async def _make_payment(
    db: AsyncSession,
    *,
    order_id: str,
    status: str = "pending",
) -> str:
    payment_id = str(uuid.uuid4())
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="mock",
            status=status,
            amount=Decimal("10.00"),
            currency="USD",
        )
    )
    await db.commit()
    return payment_id


# ---------- expire_stale_orders ----------


async def test_expire_cancels_pending_payment(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, expires_in_minutes=-15)
    payment_id = await _make_payment(db_session, order_id=order_id, status="pending")

    count = await orders_svc.expire_stale_orders(db_session)
    await db_session.commit()
    assert count == 1

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "cancelled", "pending payment must follow its expired order"

    attempts = (
        (
            await db_session.execute(
                select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)
            )
        )
        .scalars()
        .all()
    )
    cancel_attempts = [a for a in attempts if a.kind == "cancel"]
    assert cancel_attempts, "cascade-cancel must leave an audit row on payment_attempts"
    assert cancel_attempts[0].payload.get("trigger") == "order_terminated"


async def test_expire_keeps_succeeded_payment(db_session: AsyncSession) -> None:
    """A succeeded payment on an order whose follow-up expires should stay
    succeeded — only open intents are cleared."""
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, expires_in_minutes=-15)
    payment_id = await _make_payment(db_session, order_id=order_id, status="succeeded")

    await orders_svc.expire_stale_orders(db_session)
    await db_session.commit()

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"


async def test_expire_with_no_payments_is_noop(db_session: AsyncSession) -> None:
    """An order without any payment row still expires cleanly."""
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, expires_in_minutes=-15)
    count = await orders_svc.expire_stale_orders(db_session)
    await db_session.commit()
    assert count == 1
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "expired"


# ---------- admin cancel_order_admin ----------


async def test_admin_cancel_cancels_pending_payment(db_session: AsyncSession) -> None:
    admin_id = str(uuid.uuid4())
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)
    payment_id = await _make_payment(db_session, order_id=order_id, status="pending")

    await orders_svc.cancel_order_admin(db_session, order_id, admin_id=admin_id)
    await db_session.commit()

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "cancelled"


async def test_admin_cancel_does_not_touch_failed_payment(
    db_session: AsyncSession,
) -> None:
    admin_id = str(uuid.uuid4())
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)
    payment_id = await _make_payment(db_session, order_id=order_id, status="failed")

    await orders_svc.cancel_order_admin(db_session, order_id, admin_id=admin_id)
    await db_session.commit()

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "failed"
