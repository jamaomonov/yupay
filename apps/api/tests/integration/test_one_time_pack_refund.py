"""A refused one-time pack refunds itself to the balance; guests can't buy one (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.wallet import service as wallet

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio

AMOUNT = Decimal("120000")


async def _order(db: AsyncSession, tag: str, *, one_time: bool) -> tuple[Order, OrderItem]:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    sku = await db.get(Sku, item.sku_id)
    assert sku is not None
    sku.one_time_pack = one_time
    db.add(
        Payment(
            id=new_id(),
            order_id=order.id,
            provider="payme",
            status="succeeded",
            amount=AMOUNT,
            currency="UZS",
            extra_metadata={},
        )
    )
    await db.commit()
    return order, item


async def _failed(db: AsyncSession, order: Order, item: OrderItem, money: MoneyOutcome) -> str:
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="fzr",
        status="failed",
        last_error="fzr refunded the order (refund)",
        extra_metadata={"money_outcome": money.value},
    )
    db.add(task)
    await db.commit()
    return task.id


async def _balance(db: AsyncSession, user_id: str) -> Decimal:
    acc = await wallet.ensure_account(
        db, owner_type="user", owner_id=user_id, kind="user_wallet", currency="UZS"
    )
    return await wallet.balance(db, acc.id)


async def test_a_refused_one_time_pack_lands_on_the_balance(db_session: AsyncSession) -> None:
    order, item = await _order(db_session, "otp-yes", one_time=True)
    assert order.user_id is not None
    task_id = await _failed(db_session, order, item, MoneyOutcome.RETURNED)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert await _balance(db_session, order.user_id) == AMOUNT
    await db_session.refresh(order)
    assert order.status == "refunded"


async def test_an_ordinary_sku_still_waits_for_an_operator(db_session: AsyncSession) -> None:
    order, item = await _order(db_session, "otp-no", one_time=False)
    assert order.user_id is not None
    task_id = await _failed(db_session, order, item, MoneyOutcome.RETURNED)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert await _balance(db_session, order.user_id) == Decimal("0")


async def test_money_not_confirmed_back_refunds_nothing(db_session: AsyncSession) -> None:
    order, item = await _order(db_session, "otp-unknown", one_time=True)
    assert order.user_id is not None
    task_id = await _failed(db_session, order, item, MoneyOutcome.UNKNOWN)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert await _balance(db_session, order.user_id) == Decimal("0")


async def test_a_replay_refunds_once(db_session: AsyncSession) -> None:
    order, item = await _order(db_session, "otp-twice", one_time=True)
    assert order.user_id is not None
    task_id = await _failed(db_session, order, item, MoneyOutcome.RETURNED)
    for _ in range(2):
        await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
        await db_session.commit()
    assert await _balance(db_session, order.user_id) == AMOUNT


async def test_a_guest_cannot_buy_a_one_time_pack(db_session: AsyncSession) -> None:
    from yupay.core.errors import ValidationError
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    from tests.integration.test_brand_visible_retail import _seed

    sku_id = await _seed(db_session, slug="otp-guest", visible_retail=True)
    sku = await db_session.get(Sku, sku_id)
    assert sku is not None
    sku.one_time_pack = True
    await db_session.commit()
    body = OrderCreate(items=[OrderItemIn(sku_id=sku_id, qty=1, fulfillment_data={})])
    with pytest.raises(ValidationError) as refused:
        await create_order(
            db_session,
            body,
            actor=Actor(user_id=None, email="guest@example.com"),
            idempotency_key=f"otp-{new_id()}",
        )
    assert refused.value.extra == {"extra": {"reason": "login_required", "sku_ids": [sku_id]}}
