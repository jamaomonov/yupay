"""Expiry must never overwrite a payment that settled in the meantime.

The minute sweep and the read-path guard both decided on an order snapshot
loaded without a lock, then wrote ``expired`` by primary key. A settlement
that committed between that read and that write was overwritten: the
acquirer had debited the buyer, fulfilment tasks existed, and the order said
«истёк» — while the paid-after-expiry alert never fired, because the
settlement itself had seen ``pending_payment``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import yupay.api.v1  # noqa: F401  isort: skip

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yupay.modules.orders import service as orders_svc
from yupay.modules.orders.models import Order
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _stale_pending_order(factory: async_sessionmaker[AsyncSession]) -> str:
    async with factory() as db:
        user_id = str(uuid.uuid4())
        db.add(User(id=user_id, roles=[]))
        await db.flush()
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
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db.commit()
    return order_id


async def _status(factory: async_sessionmaker[AsyncSession], order_id: str) -> str:
    async with factory() as db:
        return (await db.execute(select(Order.status).where(Order.id == order_id))).scalar_one()


async def test_read_path_guard_does_not_expire_an_order_paid_after_it_was_loaded(
    db_engine,
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    order_id = await _stale_pending_order(factory)

    async with factory() as reader:
        # The customer's page view loads the order: still pending, TTL elapsed.
        order = (await reader.execute(select(Order).where(Order.id == order_id))).scalar_one()
        assert order.status == "pending_payment"

        # The acquirer's callback settles it and commits first.
        async with factory() as settler:
            await settler.execute(update(Order).where(Order.id == order_id).values(status="paid"))
            await settler.commit()

        assert await orders_svc._expire_order_inline(reader, order) is False
        await reader.commit()

    assert await _status(factory, order_id) == "paid"


async def test_sweep_skips_an_order_a_settlement_is_holding(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    order_id = await _stale_pending_order(factory)

    async with factory() as settler:
        # Settlement has written ``paid`` and holds the row, not yet committed.
        await settler.execute(update(Order).where(Order.id == order_id).values(status="paid"))

        async with factory() as sweeper:
            # Must neither wait on the settlement nor overwrite it afterwards.
            flipped = await asyncio.wait_for(orders_svc.expire_stale_orders(sweeper), timeout=5)
            await sweeper.commit()
        assert flipped == 0

        await settler.commit()

    assert await _status(factory, order_id) == "paid"
