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
        ("failed", {"status": 6}, False),  # declined: Waxpeer gave the money back
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
