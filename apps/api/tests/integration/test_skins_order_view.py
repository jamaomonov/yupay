"""The order API shows a skin line's trade to its owner (plan 3a, Task 8)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.skins.models import SkinTrade

from tests.integration.test_checkout_steam_gift import _login_user
from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


async def _owned_order(db: AsyncSession, user_id: str, tag: str, **trade: Any) -> str:
    order = await _make_paid_order(db, tag=tag)
    row = await db.get(Order, order.id)
    assert row is not None
    row.user_id = user_id
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
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


async def test_the_owner_sees_the_offer(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_user(integration_client, tg_id=940_001)
    auth = {"Authorization": f"Bearer {token}"}
    me = (await integration_client.get("/api/v1/auth/me", headers=auth)).json()
    order_id = await _owned_order(
        db_session,
        me["id"],
        "ov-1",
        status=4,
        trade_id="9393511289",
        send_until=datetime(2026, 9, 29, 12, 30, tzinfo=UTC),
        seller={"name": "darpan6awx", "avatar_url": None, "level": 12, "joined_at": None},
    )
    body = (await integration_client.get(f"/api/v1/orders/{order_id}", headers=auth)).json()
    trade = body["items"][0]["skin_trade"]
    assert trade["state"] == "offer_sent"
    assert trade["offer_url"] == "https://steamcommunity.com/tradeoffer/9393511289/"
    assert trade["seller"]["name"] == "darpan6awx"


async def test_a_line_without_a_trade_has_none(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_user(integration_client, tg_id=940_002)
    auth = {"Authorization": f"Bearer {token}"}
    me = (await integration_client.get("/api/v1/auth/me", headers=auth)).json()
    order = await _make_paid_order(db_session, tag="ov-none")
    row = await db_session.get(Order, order.id)
    assert row is not None
    row.user_id = me["id"]
    await db_session.commit()
    body = (await integration_client.get(f"/api/v1/orders/{order.id}", headers=auth)).json()
    assert body["items"][0]["skin_trade"] is None


async def test_the_order_list_reads_trades_in_one_query(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_user(integration_client, tg_id=940_003)
    auth = {"Authorization": f"Bearer {token}"}
    me = (await integration_client.get("/api/v1/auth/me", headers=auth)).json()
    for i in range(3):
        await _owned_order(db_session, me["id"], f"ov-list-{i}", status=2)
    seen: list[str] = []

    def record(_c: object, _cur: object, statement: str, *_a: object) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        body = (await integration_client.get("/api/v1/orders", headers=auth)).json()
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert [i["items"][0]["skin_trade"]["state"] for i in body["items"]] == ["buying"] * 3
    assert sum("FROM skin_trades" in s for s in seen) == 1
