"""Admin acting on skin trades: refund to the balance, retry flags, sales and margin, the customer.

Retrying reuses ``POST /admin/fulfillment/tasks/{id}/retry``; the trade row only says whether
it may be pressed (``can_retry``) and which task it is (``task_id``).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.skins.models import SkinTrade, SkinTradeLink
from yupay.modules.wallet import service as wallet

from tests.integration.test_fulfillment_async import _make_paid_order
from tests.integration.test_skins_admin_pricing import _admin_headers

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"


async def _skin(
    db: AsyncSession,
    tag: str,
    *,
    state: str,
    task_status: str | None = None,
    paid: bool = True,
    sold: str = "30.00",
    **trade: Any,
) -> tuple[Order, SkinTrade]:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    item.fulfillment_state = state
    item.unit_price_usd = Decimal(sold)
    item.fulfillment_data = {"tradelink": LINK, "slug": f"s-{tag}", "waxpeer_name": "AK"}
    task_id = None
    if task_status is not None:
        task = FulfillmentTask(
            id=new_id(),
            order_id=order.id,
            order_item_id=item.id,
            supplier="waxpeer",
            status=task_status,
            extra_metadata={"waxpeer_kind": "skin"},
        )
        db.add(task)
        task_id = task.id
    if paid:
        db.add(
            Payment(
                id=new_id(),
                order_id=order.id,
                provider="click",
                status="succeeded",
                amount=Decimal("385700"),
                currency="UZS",
                extra_metadata={},
            )
        )
    row = SkinTrade(
        id=new_id(),
        order_item_id=item.id,
        project_id=f"p-{tag}",
        listing_id=1,
        market_hash_name="AK-47 | Redline (Field-Tested)",
        paid_units=27867,
        task_id=task_id,
        **trade,
    )
    db.add(row)
    await db.commit()
    return order, row


def _find(body: dict[str, Any], trade_id: str) -> dict[str, Any]:
    return next(i for i in body["items"] if i["id"] == trade_id)


async def test_a_failed_trade_with_the_money_still_ours_can_be_refunded(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_001)
    order, row = await _skin(
        db_session, "ops-refund", state="failed", task_status="failed", reason="buy_unconfirmed"
    )
    listed = (await integration_client.get("/api/v1/admin/skins/trades", headers=headers)).json()
    before = _find(listed, row.id)
    assert (before["can_refund"], before["can_retry"], before["refunded_to"]) == (True, True, None)
    assert before["task_id"] == row.task_id

    r = await integration_client.post(
        f"/api/v1/admin/skins/trades/{row.id}/refund",
        headers={**headers, "Idempotency-Key": f"ops-refund-{new_id()}"},
    )
    assert r.status_code == 200, r.text
    after = r.json()
    assert (after["refunded_to"], after["can_refund"], after["can_retry"]) == (
        "wallet",
        False,
        False,
    )
    assert after["resolved_at"] is not None
    assert order.user_id is not None
    acc = await wallet.ensure_account(
        db_session, owner_type="user", owner_id=order.user_id, kind="user_wallet", currency="UZS"
    )
    assert await wallet.balance(db_session, acc.id) == Decimal("385700")


async def test_a_refund_needs_an_idempotency_key(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_002)
    _, row = await _skin(db_session, "ops-nokey", state="failed", task_status="failed")
    r = await integration_client.post(
        f"/api/v1/admin/skins/trades/{row.id}/refund", headers=headers
    )
    assert r.status_code in (400, 422), r.text


async def test_a_skin_on_its_way_cannot_be_refunded(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_003)
    _, row = await _skin(db_session, "ops-flight", state="in_progress", status=4)
    listed = (await integration_client.get("/api/v1/admin/skins/trades", headers=headers)).json()
    assert _find(listed, row.id)["can_refund"] is False
    r = await integration_client.post(
        f"/api/v1/admin/skins/trades/{row.id}/refund",
        headers={**headers, "Idempotency-Key": f"ops-flight-{new_id()}"},
    )
    assert r.status_code == 409, r.text


async def test_sales_and_margin_over_a_period(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_004)
    before = (
        await integration_client.get("/api/v1/admin/skins/summary?days=30", headers=headers)
    ).json()
    await _skin(db_session, "sum-a", state="delivered", sold="30.00", status=4, bought_units=27000)
    await _skin(db_session, "sum-b", state="delivered", sold="12.50", status=5, bought_units=11000)
    await _skin(db_session, "sum-c", state="failed", sold="9.00", status=6)
    await _skin(db_session, "sum-d", state="in_progress", sold="5.00", status=0)
    old, _ = await _skin(db_session, "sum-old", state="delivered", sold="99", bought_units=1)
    old_row = (
        await db_session.execute(select(SkinTrade).where(SkinTrade.project_id == "p-sum-old"))
    ).scalar_one()
    old_row.created_at = now() - timedelta(days=45)
    await db_session.commit()

    body = (
        await integration_client.get("/api/v1/admin/skins/summary?days=30", headers=headers)
    ).json()

    def delta(key: str, sub: str) -> Decimal:
        return Decimal(str(body[key][sub])) - Decimal(str(before[key][sub]))

    assert delta("sold", "count") == 2
    assert delta("sold", "revenue_usd") == Decimal("42.50")
    assert delta("sold", "cost_usd") == Decimal("38.000")
    assert delta("sold", "margin_usd") == Decimal("4.500")
    assert delta("failed", "count") == 1
    assert delta("in_flight", "count") == 1
    assert body["days"] == 30
    assert body["by_day"], "a day with sales is listed"


async def test_the_customer_card_shows_their_steam_accounts_and_skins(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session, tg_id=951_005)
    order, row = await _skin(db_session, "cust", state="delivered", status=5)
    assert order.user_id is not None
    db_session.add(SkinTradeLink(user_id=order.user_id, url=LINK, steam_id=76561199000000000))
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/skins/customers/{order.user_id}", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"]["steam_id"] == "76561199000000000"
    assert body["saved"]["profile_url"] == "https://steamcommunity.com/profiles/76561199000000000"
    # The token is a credential: the admin sees the account, never the link.
    assert "LBCWEQ8s" not in r.text
    accounts = {a["steam_id"]: a["orders"] for a in body["accounts"]}
    assert accounts == {str(1039652352 + 76561197960265728): 1}
    assert [t["id"] for t in body["trades"]] == [row.id]
