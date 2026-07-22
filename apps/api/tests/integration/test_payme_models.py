"""Integration tests for the ``payme_transactions`` data model.

Covers: inserting a ``PaymeTransaction`` against the real (testcontainers)
Postgres, the ``UNIQUE(payme_id)`` guard that makes Payme's Merchant API
methods idempotent against replays, and the ``state`` CHECK that only
Payme's own encoding (``1``/``2``/``-1``/``-2``) is a legal value.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.orders.models import Order
from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _make_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    return user_id


async def _make_order(db: AsyncSession, *, user_id: str) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=Decimal("130000.00"),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db.flush()
    return order_id


async def test_payme_transaction_round_trips(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    txn = PaymeTransaction(
        id=str(uuid.uuid4()),
        payme_id="686cbf0f0a6e2d3d5c0e1234",
        order_id=order_id,
        amount_tiyin=1_300_000,
        state=1,
    )
    db_session.add(txn)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(PaymeTransaction).where(PaymeTransaction.id == txn.id))
    ).scalar_one()
    assert fetched.payment_id is None
    assert fetched.reason is None
    assert fetched.create_time == 0
    assert fetched.perform_time == 0
    assert fetched.cancel_time == 0
    assert fetched.fiscal_data == {}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_payme_transaction_rejects_duplicate_payme_id(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_a = await _make_order(db_session, user_id=user_id)
    order_b = await _make_order(db_session, user_id=user_id)

    db_session.add(
        PaymeTransaction(
            id=str(uuid.uuid4()),
            payme_id="dup-payme-id",
            order_id=order_a,
            amount_tiyin=1_000_000,
            state=1,
        )
    )
    await db_session.flush()

    db_session.add(
        PaymeTransaction(
            id=str(uuid.uuid4()),
            payme_id="dup-payme-id",
            order_id=order_b,
            amount_tiyin=2_000_000,
            state=1,
        )
    )
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_payme_transaction_state_check_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    db_session.add(
        PaymeTransaction(
            id=str(uuid.uuid4()),
            payme_id="bad-state-id",
            order_id=order_id,
            amount_tiyin=1_000_000,
            state=3,
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()
