"""Integration tests for the ``uzum_transactions`` data model.

Covers: inserting an ``UzumTransaction`` against the real (testcontainers)
Postgres, the ``UNIQUE(trans_id)`` guard that makes Uzum's Merchant API
methods idempotent against replays, and the ``status`` CHECK that only the
four legal values (``CREATED``/``CONFIRMED``/``REVERSED``/``FAILED``) are
accepted. This is the model-round-trip smoke test for the inverted-webhook
twin of ``payme_transactions`` — see ``test_payme_models.py`` for the pattern
this mirrors. Service-level tests (analogous to ``test_payme_service.py``)
land once ``yupay.modules.uzum.service`` exists.
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
from yupay.modules.orders.models import Order
from yupay.modules.users.models import User
from yupay.modules.uzum.models import UzumTransaction

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


async def test_uzum_transaction_round_trips(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    txn = UzumTransaction(
        id=new_id(),
        trans_id="686cbf0f0a6e2d3d5c0e1234",
        order_id=order_id,
        amount_tiyin=1_300_000,
        status="CREATED",
        create_time=1_700_000_000_000,
    )
    db_session.add(txn)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(UzumTransaction).where(UzumTransaction.id == txn.id))
    ).scalar_one()
    assert fetched.trans_id == "686cbf0f0a6e2d3d5c0e1234"
    assert fetched.order_id == order_id
    assert fetched.payment_id is None
    assert fetched.amount_tiyin == 1_300_000
    assert fetched.status == "CREATED"
    assert fetched.service_id is None
    assert fetched.create_time == 1_700_000_000_000
    assert fetched.confirm_time is None
    assert fetched.reverse_time is None
    assert fetched.payment_source == {}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_uzum_transaction_rejects_duplicate_trans_id(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_a = await _make_order(db_session, user_id=user_id)
    order_b = await _make_order(db_session, user_id=user_id)

    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="dup-trans-id",
            order_id=order_a,
            amount_tiyin=1_000_000,
            status="CREATED",
        )
    )
    await db_session.flush()

    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="dup-trans-id",
            order_id=order_b,
            amount_tiyin=2_000_000,
            status="CREATED",
        )
    )
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_uzum_transaction_status_check_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="bad-status-id",
            order_id=order_id,
            amount_tiyin=1_000_000,
            status="BOGUS",
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()
