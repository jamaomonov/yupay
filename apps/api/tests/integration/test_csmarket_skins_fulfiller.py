"""Buying a skin through csmarket and following the trade (ADR-0098).

A fake client stands in for csmarket; the database is real, so the ``skin_trades`` mirror
is checked as the order page and the sweeps will read it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.service import _line_route
from yupay.modules.fulfillment.skin_sweeps import skin_recheck_seconds
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.fulfillment.suppliers.csmarket_client import (
    CsmarketError,
    CsmarketUnavailableError,
    CsmOrder,
    CsmTrade,
)
from yupay.modules.fulfillment.suppliers.csmarket_skins import buy, skin_status, trade_row
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"
NAME = "AK-47 | Redline (Field-Tested)"
KEY = "task-key-csm"
OFFER = "rBGDFCIOesyZ9-DMdmHEEJA8jPyS5w6v"


def _order(status: str = "buying", **over: Any) -> CsmOrder:
    base: dict[str, Any] = {
        "order_id": "A1B2C3D4",
        "client_order_id": KEY,
        "status": status,
        "price_units": 27000,
        "item_id": "csm-ak",
        "market_hash_name": NAME,
        "trade": None,
        "refund_units": None,
        "refund_reason": None,
    }
    base.update(over)
    return CsmOrder(**base)


class _Client:
    """Scripted csmarket: ``refuse`` codes per call, ``orders`` answered by GET."""

    def __init__(
        self,
        *,
        refuse: list[str] | None = None,
        create_error: Exception | None = None,
        existing: CsmOrder | None = None,
        current: CsmOrder | None = None,
    ) -> None:
        self.refuse = list(refuse or [])
        self.create_error = create_error
        self.existing = existing
        self.current = current
        self.sent: list[dict[str, Any]] = []
        self.read: list[str] = []

    async def create_order(
        self,
        *,
        item_id: str,
        offer_id: str | None,
        max_price_units: int,
        trade_link: str,
        client_order_id: str,
    ) -> tuple[CsmOrder, bool]:
        self.sent.append(
            {
                "item_id": item_id,
                "offer_id": offer_id,
                "cap": max_price_units,
                "key": client_order_id,
            }
        )
        if self.create_error is not None:
            raise self.create_error
        if self.refuse:
            code = self.refuse.pop(0)
            raise CsmarketError(
                "no", status=402 if code == "insufficient_balance" else 409, code=code
            )
        if self.existing is not None:
            return self.existing, False
        return _order(), True

    async def order(self, order_id: str) -> CsmOrder:
        self.read.append(order_id)
        assert self.current is not None
        return self.current


async def _item(db: AsyncSession, tag: str, **over: Any) -> OrderItem:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    item.fulfillment_data = {
        "slug": "ak-47-redline-field-tested",
        "listing_id": 123456789,
        "tradelink": LINK,
        "market_hash_name": NAME,
        "phase": "",
        "name": NAME,
        "expected_units": 27867,
        "supplier": "csmarket",
        "offer_id": OFFER,
        "source_item_id": "csm-ak",
        **over,
    }
    await db.commit()
    return item


async def _task(db: AsyncSession, item: OrderItem) -> FulfillmentTask:
    task = FulfillmentTask(
        id=new_id(),
        order_id=item.order_id,
        order_item_id=item.id,
        supplier="csmarket",
        status="in_progress",
        external_order_id=KEY,
        extra_metadata={"waxpeer_kind": "skin"},
    )
    db.add(task)
    await db.commit()
    return task


async def _buy(db: AsyncSession, item: OrderItem, client: _Client) -> Any:
    row = await trade_row(db, item, KEY)
    return await buy(client, db=db, item=item, row=row, key=KEY)


async def _row(db: AsyncSession) -> SkinTrade:
    row = (await db.execute(select(SkinTrade))).scalar_one()
    await db.refresh(row)
    return row


async def test_a_line_names_its_supplier() -> None:
    assert _line_route(OrderItem(fulfillment_data={"supplier": "csmarket"})) == "csmarket"
    assert _line_route(OrderItem(fulfillment_data={"supplier": "g2b"})) is None
    assert _line_route(OrderItem(fulfillment_data={})) is None


async def test_buys_the_chosen_offer_under_the_paid_cap(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-ok")
    client = _Client()
    result = await _buy(db_session, item, client)
    assert result.outcome == "in_progress"
    assert result.external_order_id == KEY
    assert client.sent == [{"item_id": "csm-ak", "offer_id": OFFER, "cap": 27867, "key": KEY}]
    row = await _row(db_session)
    assert (row.supplier, row.supplier_order_id, row.offer_id) == ("csmarket", "A1B2C3D4", OFFER)
    assert (row.status, row.bought_units) == (0, 27000)


async def test_a_gone_offer_retries_once_without_it_under_the_same_cap(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "csm-gone")
    client = _Client(refuse=["offer_gone"])
    result = await _buy(db_session, item, client)
    assert result.outcome == "in_progress"
    assert [s["offer_id"] for s in client.sent] == [OFFER, None]
    assert {s["cap"] for s in client.sent} == {27867}
    assert {s["key"] for s in client.sent} == {KEY}


async def test_refused_twice_is_sold_out_and_returned(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-sold")
    result = await _buy(db_session, item, _Client(refuse=["offer_gone", "price_above_max"]))
    assert (result.outcome, result.error, result.money_outcome) == (
        "failed",
        "sold_out",
        MoneyOutcome.RETURNED,
    )
    assert (await _row(db_session)).reason == "sold_out"


async def test_no_balance_returns_the_money_and_says_why(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-402")
    client = _Client(refuse=["insufficient_balance"])
    result = await _buy(db_session, item, client)
    assert (result.outcome, result.error, result.money_outcome) == (
        "failed",
        "supplier_low_balance",
        MoneyOutcome.RETURNED,
    )
    assert result.extra_metadata["required_units"] == 27867
    assert len(client.sent) == 1


async def test_a_lost_answer_is_settled_by_sending_the_same_purchase_again(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "csm-lost")
    lost = await _buy(db_session, item, _Client(create_error=CsmarketUnavailableError("HTTP 502")))
    assert lost.outcome == "in_progress"
    assert lost.extra_metadata["buy_pending"] is True
    assert (await _row(db_session)).supplier_order_id is None

    task = await _task(db_session, item)
    # The first request did land: csmarket answers the repeat with that order.
    again = _Client(existing=_order("trade_sent"))
    status = await skin_status(again, db=db_session, task=task)
    assert status.outcome == "in_progress"
    assert again.sent[0]["key"] == KEY
    row = await _row(db_session)
    assert (row.supplier_order_id, row.status) == ("A1B2C3D4", 4)


async def test_status_follows_the_trade_to_delivered(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-flow")
    await _buy(db_session, item, _Client())
    task = await _task(db_session, item)
    accepted = datetime(2026, 10, 9, 8, 25, tzinfo=UTC)
    trade = CsmTrade(
        offer_sent_at=accepted - timedelta(minutes=3),
        accepted_at=accepted,
        release_at=accepted + timedelta(days=7),
        steam_offer_id="7612345678",
        seller_name="seller",
    )
    sent = _Client(
        current=_order("trade_sent", trade=CsmTrade(None, None, None, "7612345678", "seller"))
    )
    assert (await skin_status(sent, db=db_session, task=task)).outcome == "in_progress"
    row = await _row(db_session)
    assert (row.status, row.trade_id, row.release_date) == (4, "7612345678", None)
    assert row.seller == {"name": "seller"}
    assert sent.read == ["A1B2C3D4"]

    done = _Client(current=_order("delivered", trade=trade))
    status = await skin_status(done, db=db_session, task=task)
    assert status.outcome == "succeeded"
    assert status.artifact is not None
    assert status.artifact["trade_id"] == "7612345678"
    row = await _row(db_session)
    assert row.release_date == accepted + timedelta(days=7)
    assert row.status == 4  # accepted, still under Steam's protection


async def test_a_refund_after_the_offer_reads_as_not_accepted(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-declined")
    await _buy(db_session, item, _Client(existing=_order("trade_sent")))
    task = await _task(db_session, item)
    refunded = _Client(
        current=_order("refunded", refund_units=27000, refund_reason="supplier_refused")
    )
    status = await skin_status(refunded, db=db_session, task=task)
    assert (status.outcome, status.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    row = await _row(db_session)
    assert (row.status, row.reason) == (6, "not accepted")


async def test_a_refund_before_any_offer_reads_as_sold_out(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-nooffer")
    await _buy(db_session, item, _Client())
    task = await _task(db_session, item)
    refunded = _Client(current=_order("refunded", refund_units=27000, refund_reason="sold_out"))
    status = await skin_status(refunded, db=db_session, task=task)
    assert status.money_outcome is MoneyOutcome.RETURNED
    row = await _row(db_session)
    assert (row.status, row.reason) == (None, "sold_out")


async def test_a_line_without_csmarket_ids_is_never_bought(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-bare", source_item_id=None)
    client = _Client()
    result = await _buy(db_session, item, client)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert client.sent == []


async def test_csmarket_trades_are_looked_at_less_often(db_session: AsyncSession) -> None:
    item = await _item(db_session, "csm-recheck")
    await _buy(db_session, item, _Client())
    task = await _task(db_session, item)
    row = await _row(db_session)
    row.task_id = task.id
    await db_session.commit()
    assert await skin_recheck_seconds(db_session, task_id=task.id) == 15
    row.status = 4
    await db_session.commit()
    assert await skin_recheck_seconds(db_session, task_id=task.id) == 30


async def test_the_fast_sweep_picks_up_csmarket_tasks(db_session: AsyncSession) -> None:
    from yupay.modules.fulfillment.skin_sweeps import due_skin_task_ids

    item = await _item(db_session, "csm-due")
    task = await _task(db_session, item)
    assert task.id in await due_skin_task_ids(db_session)
