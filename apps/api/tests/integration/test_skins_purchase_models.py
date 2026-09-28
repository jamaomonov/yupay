"""Purchase tables (plan 3a, Task 1): one trade per order line, one saved link per user,
and a supplier mapping of kind ``skin``."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade, SkinTradeLink

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


async def _line(db: AsyncSession, tag: str) -> OrderItem:
    order = await _make_paid_order(db, tag=tag)
    return (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()


def _trade(order_item_id: str, project_id: str) -> SkinTrade:
    return SkinTrade(
        id=new_id(),
        order_item_id=order_item_id,
        project_id=project_id,
        listing_id=53860909078,
        market_hash_name="Galil AR | Grey Smoke (Field-Tested)",
        phase="",
        paid_units=5,
    )


async def test_a_trade_round_trips_with_waxpeer_state(db_session: AsyncSession) -> None:
    line = await _line(db_session, "skin-trade")
    db_session.add(_trade(line.id, "p-1"))
    await db_session.commit()
    row = (await db_session.execute(select(SkinTrade))).scalar_one()
    assert row.status is None
    assert row.is_released is False
    assert row.seller == {}


async def test_one_trade_per_order_line(db_session: AsyncSession) -> None:
    line = await _line(db_session, "skin-trade-dup")
    line_id = line.id
    db_session.add(_trade(line_id, "p-2"))
    await db_session.commit()
    db_session.add(_trade(line_id, "p-3"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_a_user_keeps_one_saved_trade_link(db_session: AsyncSession) -> None:
    order = await _make_paid_order(db_session, tag="skin-link")
    user_id = order.user_id
    link = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcdefgh"
    db_session.add(SkinTradeLink(user_id=user_id, url=link, steam_id=76561197960265729))
    await db_session.commit()
    assert (await db_session.get(SkinTradeLink, user_id)) is not None


async def test_a_skin_mapping_is_allowed(db_session: AsyncSession) -> None:
    line = await _line(db_session, "skin-map")
    db_session.add(
        SkuSupplierMapping(
            sku_id=line.sku_id,
            supplier_slug="waxpeer",
            kind="skin",
            external_product_id="cs2-skin",
        )
    )
    await db_session.commit()
