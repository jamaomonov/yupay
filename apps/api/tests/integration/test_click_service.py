"""Integration tests for the ``click_transactions`` data model.

This is a model-only smoke test (mirrors the model section of
``test_uzum_service.py``) — the Click Shop API service/routes land in a later
task. Coverage: inserting a ``ClickTransaction`` against the real
(testcontainers) Postgres and confirming ``merchant_prepare_id`` is DB-assigned
(IDENTITY, not app-supplied), the ``UNIQUE(click_trans_id, service_id)`` guard
that makes ``/prepare``/``/complete`` idempotent against replays, and the
``status`` CHECK that only the three legal values (``PREPARED``/``CONFIRMED``/
``CANCELLED``) are accepted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.click.models import ClickTransaction
from yupay.modules.orders.models import Order
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

SERVICE_ID = 108149


async def _make_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    return user_id


async def _make_order(
    db: AsyncSession,
    *,
    user_id: str,
    status: str = "pending_payment",
    total_charged: Decimal = Decimal("130000.00"),
) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status=status,
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=total_charged,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db.flush()
    return order_id


async def test_click_transaction_round_trips(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    txn = ClickTransaction(
        id=new_id(),
        click_trans_id=4_294_967_295,
        service_id=SERVICE_ID,
        order_id=order_id,
        amount=Decimal("130000.000000"),
        status="PREPARED",
    )
    db_session.add(txn)
    await db_session.flush()
    await db_session.refresh(txn)

    assert isinstance(txn.merchant_prepare_id, int)
    assert txn.merchant_prepare_id > 0

    fetched = (
        await db_session.execute(select(ClickTransaction).where(ClickTransaction.id == txn.id))
    ).scalar_one()
    assert fetched.merchant_prepare_id == txn.merchant_prepare_id
    assert fetched.click_trans_id == 4_294_967_295
    assert fetched.service_id == SERVICE_ID
    assert fetched.order_id == order_id
    assert fetched.payment_id is None
    assert fetched.amount == Decimal("130000.000000")
    assert fetched.status == "PREPARED"
    assert fetched.click_paydoc_id is None
    assert fetched.prepare_time is None
    assert fetched.complete_time is None
    assert fetched.cancel_time is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_click_transaction_rejects_duplicate_trans_service(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_a = await _make_order(db_session, user_id=user_id)
    order_b = await _make_order(db_session, user_id=user_id)

    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=111,
            service_id=SERVICE_ID,
            order_id=order_a,
            amount=Decimal("10000.000000"),
            status="PREPARED",
        )
    )
    await db_session.flush()

    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=111,
            service_id=SERVICE_ID,
            order_id=order_b,
            amount=Decimal("20000.000000"),
            status="PREPARED",
        )
    )
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_click_transaction_status_check_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=222,
            service_id=SERVICE_ID,
            order_id=order_id,
            amount=Decimal("10000.000000"),
            status="BOGUS",
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()
