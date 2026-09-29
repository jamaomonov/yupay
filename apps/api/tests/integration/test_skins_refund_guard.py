"""A skin still on its way blocks refunds: the buyer would get the skin and the money.

Waxpeer cannot recall an offer we paid for, so while a trade is being bought or sent an
acquirer cancel (Payme, Uzum, Paynet) or an admin refund would hand over both.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.orders.models import OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.refund_guard import skin_trade_in_flight

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


async def _order(db: AsyncSession, tag: str, *, state: str, **trade: Any) -> str:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    item.fulfillment_state = state
    db.add(
        SkinTrade(
            id=new_id(),
            order_item_id=item.id,
            project_id=f"p-{tag}",
            listing_id=1,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            paid_units=27867,
            **trade,
        )
    )
    await db.commit()
    return order.id


@pytest.mark.parametrize(
    ("state", "trade", "blocked"),
    [
        ("in_progress", {"status": None}, True),  # buying: the buy may be in flight
        ("in_progress", {"status": 0}, True),
        ("in_progress", {"status": 4}, True),  # the offer is in Steam
        ("delivered", {"status": 4}, False),  # received: the delivered-goods guard's job
        ("failed", {"status": 6}, True),  # failed, but no task says where the money is
    ],
)
async def test_only_a_trade_on_its_way_blocks(
    db_session: AsyncSession, state: str, trade: dict[str, Any], blocked: bool
) -> None:
    order_id = await _order(db_session, f"rg-{state}-{trade['status']}", state=state, **trade)
    assert await skin_trade_in_flight(db_session, order_id) is blocked


async def test_an_order_without_skins_is_never_blocked(db_session: AsyncSession) -> None:
    order = await _make_paid_order(db_session, tag="rg-plain")
    assert await skin_trade_in_flight(db_session, order.id) is False


@pytest.mark.parametrize("module", ["payme", "uzum", "paynet"])
async def test_an_acquirer_cancel_is_refused_mid_trade(
    db_session: AsyncSession, module: str
) -> None:
    import importlib

    svc = importlib.import_module(f"yupay.modules.{module}.service")
    order_id = await _order(db_session, f"rg-acq-{module}", state="in_progress", status=4)
    assert await svc._any_goods_delivered(db_session, order_id) is True


async def test_an_admin_refund_is_refused_mid_trade(db_session: AsyncSession) -> None:
    from yupay.modules.payments.service import refund_admin

    order_id = await _order(db_session, "rg-admin", state="in_progress", status=4)
    payment = Payment(
        id=new_id(),
        order_id=order_id,
        provider="wallet",
        status="succeeded",
        amount=Decimal("385700"),
        currency="UZS",
        extra_metadata={},
    )
    db_session.add(payment)
    await db_session.commit()
    with pytest.raises(ConflictError) as err:
        await refund_admin(db_session, payment_id=payment.id, admin_id=new_id())
    assert err.value.extra["reason"] == "skin_trade_in_flight"


async def _failed_with(db: AsyncSession, tag: str, money: str, *, resolved: bool = False) -> str:
    from yupay.core.clock import now
    from yupay.modules.fulfillment.models import FulfillmentTask

    order_id = await _order(db, tag, state="failed", status=None, reason="ambiguous_trade")
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order_id))).scalar_one()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order_id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="failed",
        extra_metadata={"waxpeer_kind": "skin", "money_outcome": money},
    )
    db.add(task)
    row = (
        await db.execute(select(SkinTrade).where(SkinTrade.order_item_id == item.id))
    ).scalar_one()
    row.task_id = task.id
    if resolved:
        row.resolved_at = now()
    await db.commit()
    return order_id


@pytest.mark.parametrize(
    ("money", "resolved", "blocked"),
    [
        ("unknown", False, True),  # ambiguous: an offer may still be open in Steam
        ("unknown", True, False),  # an operator checked Waxpeer and marked it settled
        ("returned", False, False),
        ("spent", False, False),
    ],
)
async def test_a_failure_we_cannot_account_for_still_blocks(
    db_session: AsyncSession, money: str, resolved: bool, blocked: bool
) -> None:
    order_id = await _failed_with(
        db_session, f"rg-fail-{money}-{resolved}", money, resolved=resolved
    )
    assert await skin_trade_in_flight(db_session, order_id) is blocked
