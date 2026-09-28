"""``GET /admin/skins/trades``: every skin trade, newest first, and the ones a human must see."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.core.clock import now
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade

from tests.integration.test_fulfillment_async import _make_paid_order
from tests.integration.test_skins_admin_pricing import _admin_headers, _login_user

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


async def _trade(db: AsyncSession, tag: str, minutes: int, **over: Any) -> tuple[str, str]:
    """A paid order with one skin trade row, created ``minutes`` after ``_T0``."""
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    fields: dict[str, Any] = {
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "paid_units": 27867,
        **over,
    }
    row = SkinTrade(
        id=new_id(),
        order_item_id=item.id,
        project_id=f"p-{tag}",
        listing_id=1,
        created_at=_T0 + timedelta(minutes=minutes),
        **fields,
    )
    db.add(row)
    await db.commit()
    return order.id, row.id


async def _get(client: AsyncClient, headers: dict[str, str], **params: str) -> dict[str, Any]:
    r = await client.get("/api/v1/admin/skins/trades", params=params, headers=headers)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_lists_newest_first_with_a_total(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_001)
    await _trade(db_session, "old", 0, status=5, is_released=True)
    order_id, _ = await _trade(
        db_session,
        "new",
        5,
        status=4,
        trade_id="9393511289",
        seller={"name": "darpan6awx"},
        bought_units=27000,
    )
    body = await _get(integration_client, headers)
    assert body["total"] == 2
    first = body["items"][0]
    assert first["order_id"] == order_id
    assert first["state"] == "offer_sent"
    assert first["seller_name"] == "darpan6awx"
    assert first["paid_units"] == 27867
    assert first["bought_units"] == 27000
    assert first["attention"] is False


async def test_active_leaves_out_settled_trades(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_002)
    await _trade(db_session, "released", 0, status=5, is_released=True)
    await _trade(db_session, "declined", 1, status=6, reason="Buyer failed to accept")
    _, protected = await _trade(
        db_session, "protected", 2, status=4, release_date=_T0 + timedelta(days=7)
    )
    _, buying = await _trade(db_session, "buying", 3, status=0)
    body = await _get(integration_client, headers, view="active")
    assert {i["id"] for i in body["items"]} == {protected, buying}
    assert body["total"] == 2


async def test_attention_is_what_a_human_must_settle(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_003)
    _, rollback = await _trade(
        db_session, "rollback", 0, status=6, penalties={"amount": 100}, is_released=False
    )
    _, unconfirmed = await _trade(db_session, "unconf", 1, reason="buy_unconfirmed")
    await _trade(db_session, "declined", 2, status=6, reason="Buyer failed to accept")
    await _trade(db_session, "fine", 3, status=4)
    body = await _get(integration_client, headers, view="attention")
    assert {i["id"] for i in body["items"]} == {rollback, unconfirmed}
    assert all(i["attention"] for i in body["items"])


async def test_searches_by_order_id_prefix_and_name(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_004)
    order_id, _ = await _trade(db_session, "a", 0, status=4)
    await _trade(db_session, "b", 1, status=4, market_hash_name="AWP | Asiimov (Field-Tested)")
    by_order = await _get(integration_client, headers, q=order_id[:13])
    assert [i["order_id"] for i in by_order["items"]] == [order_id]
    by_name = await _get(integration_client, headers, q="asiimov")
    assert [i["market_hash_name"] for i in by_name["items"]] == ["AWP | Asiimov (Field-Tested)"]


async def test_admins_only(integration_client: AsyncClient) -> None:
    token = await _login_user(integration_client, tg_id=950_005)
    r = await integration_client.get(
        "/api/v1/admin/skins/trades", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


async def test_a_resolved_trade_leaves_the_attention_view(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_006)
    _, trade_id = await _trade(db_session, "resolve", 0, reason="ambiguous_trade")
    r = await integration_client.post(
        f"/api/v1/admin/skins/trades/{trade_id}/resolve",
        headers={**headers, "Idempotency-Key": "resolve-key-0000001"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["resolved_at"] is not None
    assert r.json()["attention"] is False
    assert (await _get(integration_client, headers, view="attention"))["total"] == 0
    everything = await _get(integration_client, headers)
    assert everything["items"][0]["resolved_at"] is not None


async def test_resolving_an_unknown_trade_is_404(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_007)
    r = await integration_client.post(
        f"/api/v1/admin/skins/trades/{new_id()}/resolve",
        headers={**headers, "Idempotency-Key": "resolve-key-0000002"},
    )
    assert r.status_code == 404


async def _pending(db: AsyncSession, tag: str, *, minutes_ago: int) -> str:
    """An in-flight skin buy whose lookup failed (``buy_pending``), no Waxpeer status yet."""
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="in_progress",
        external_order_id=f"p-{tag}",
        extra_metadata={"waxpeer_kind": "skin", "buy_pending": True},
        created_at=now() - timedelta(minutes=minutes_ago),
    )
    row = SkinTrade(
        id=new_id(),
        order_item_id=item.id,
        task_id=task.id,
        project_id=f"p-{tag}",
        listing_id=1,
        market_hash_name="AK-47 | Redline (Field-Tested)",
        paid_units=27867,
    )
    db.add_all([task, row])
    await db.commit()
    return row.id


async def test_a_buy_pending_for_seconds_is_not_attention_but_a_stuck_one_is(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_008)
    await _pending(db_session, "pend-fresh", minutes_ago=0)
    stuck = await _pending(db_session, "pend-stuck", minutes_ago=10)
    body = await _get(integration_client, headers, view="attention")
    assert [i["id"] for i in body["items"]] == [stuck]
    flags = {i["id"]: i["attention"] for i in (await _get(integration_client, headers))["items"]}
    assert flags[stuck] is True
    assert list(flags.values()).count(True) == 1


async def test_a_penalty_that_is_not_an_object_is_no_rollback(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_009)
    _, zero = await _trade(db_session, "pen-zero", 0, status=6, penalties=0)
    body = await _get(integration_client, headers, view="attention")
    assert body["total"] == 0
    flags = {i["id"]: i["attention"] for i in (await _get(integration_client, headers))["items"]}
    assert flags[zero] is False


async def test_search_wildcards_are_literal(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=950_010)
    await _trade(db_session, "wild", 0, status=4)
    assert (await _get(integration_client, headers, q="_"))["total"] == 0
    assert (await _get(integration_client, headers, q="%"))["total"] == 0
