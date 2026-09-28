"""Buying a skin on Waxpeer and following the trade (plan 3a, Task 5).

A fake client stands in for Waxpeer; the database is real, so the ``skin_trades``
mirror is checked as it will be read by the order page and the sweeps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerError,
    WaxpeerUnavailableError,
)
from yupay.modules.fulfillment.suppliers.waxpeer_skins import fulfill_skin, skin_status
from yupay.modules.fulfillment.suppliers.waxpeer_trades import (
    WaxpeerBuy,
    WaxpeerBuyRefusedError,
    WaxpeerTrade,
)
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"
NAME = "AK-47 | Redline (Field-Tested)"
KEY = "task-key-1"
CHOSEN = 111
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _trade(status: int, **over: Any) -> WaxpeerTrade:
    base = WaxpeerTrade(
        id=30717201,
        project_id=KEY,
        status=status,
        trade_id="9393511289" if status >= 2 else None,
        done=status in (5, 6),
        reason=None,
        release_date=None,
        is_released=False,
        send_until=NOW + timedelta(minutes=30),
        price_units=27867,
        penalties=None,
        seller={"name": "darpan6awx", "avatar_url": None, "level": 12, "joined_at": None},
    )
    return replace(base, **over)


class _Client:
    """Scripted Waxpeer: ``refuse`` item ids, ``live`` listings, ``trades`` lookups."""

    def __init__(
        self,
        *,
        trades: list[WaxpeerTrade] | None = None,
        refuse: set[int] | None = None,
        live: list[dict[str, Any]] | None = None,
        buy_error: Exception | None = None,
        lookup_error: Exception | None = None,
    ) -> None:
        self.trades = trades or []
        self.refuse = refuse or set()
        self.live = live or []
        self.buy_error = buy_error
        self.lookup_error = lookup_error
        self.bought: list[tuple[int, int]] = []

    async def check_project_ids(self, ids: Sequence[str]) -> list[WaxpeerTrade]:
        if self.lookup_error:
            raise self.lookup_error
        return [t for t in self.trades if t.project_id in ids]

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        if self.buy_error:
            raise self.buy_error
        if item_id in self.refuse:
            raise WaxpeerBuyRefusedError("Item not found", new_price=None)
        self.bought.append((item_id, price_units))
        return WaxpeerBuy(id=30717201, price_units=price_units)

    async def search_listings(self, names: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        return {names[0]: self.live}


async def _item(db: AsyncSession, tag: str, *, expected_units: int = 27867) -> OrderItem:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    item.fulfillment_data = {
        "slug": "ak-47-redline-field-tested",
        "listing_id": CHOSEN,
        "tradelink": LINK,
        "market_hash_name": NAME,
        "phase": "",
        "name": NAME,
        "expected_units": expected_units,
    }
    await db.commit()
    return item


async def _task(db: AsyncSession, item: OrderItem, **meta: Any) -> FulfillmentTask:
    task = FulfillmentTask(
        id=new_id(),
        order_id=item.order_id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="in_progress",
        external_order_id=KEY,
        extra_metadata={"waxpeer_kind": "skin", **meta},
    )
    db.add(task)
    await db.commit()
    return task


async def _row(db: AsyncSession) -> SkinTrade:
    return (await db.execute(select(SkinTrade))).scalar_one()


async def test_buys_the_chosen_listing_at_the_paid_units(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-buy")
    client = _Client()
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert result.external_order_id == KEY
    assert result.extra_metadata["waxpeer_kind"] == "skin"
    assert client.bought == [(CHOSEN, 27867)]
    row = await _row(db_session)
    assert (row.project_id, row.waxpeer_id, row.bought_units) == (KEY, 30717201, 27867)


async def test_a_sold_listing_is_replaced_by_a_same_name_one_not_dearer(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-sub")
    client = _Client(
        refuse={CHOSEN},
        live=[
            {"item_id": 222, "price": 28000, "auto": True},  # dearer than paid: skipped
            {"item_id": 333, "price": 27500, "auto": True},
            {"item_id": 444, "price": 27000, "auto": False},  # manual seller: never
        ],
    )
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert client.bought == [(333, 27500)]
    assert (await _row(db_session)).listing_id == 333


async def test_no_replacement_fails_with_the_money_back(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-none")
    client = _Client(refuse={CHOSEN}, live=[{"item_id": 222, "price": 99999, "auto": True}])
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert result.error == "sold_out"


async def test_a_replayed_task_adopts_the_earlier_purchase(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-replay")
    client = _Client(trades=[_trade(2)])
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert client.bought == []
    assert (await _row(db_session)).status == 2


async def test_a_lost_buy_response_is_parked_not_retried(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-lost")
    client = _Client(buy_error=WaxpeerUnavailableError("timeout"))
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert "buy_unconfirmed_at" in result.extra_metadata


async def test_low_balance_is_the_soft_path(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-low")
    client = _Client(buy_error=WaxpeerError("Not enough balance", status=200))
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "failed"
    assert result.money_outcome is None
    assert result.error == "supplier_low_balance"


async def test_status_follows_the_offer_to_acceptance(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-status")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    task = await _task(db_session, item)

    sent = await skin_status(_Client(trades=[_trade(4)]), db=db_session, task=task)
    assert sent.outcome == "in_progress"
    row = await _row(db_session)
    assert (row.status, row.trade_id, row.accepted_at) == (4, "9393511289", None)
    assert row.seller["name"] == "darpan6awx"

    release = NOW + timedelta(days=7)
    accepted = await skin_status(
        _Client(trades=[_trade(4, release_date=release)]), db=db_session, task=task
    )
    assert accepted.outcome == "succeeded"
    assert accepted.artifact_kind == "topup_receipt"
    assert accepted.artifact is not None
    assert accepted.artifact["kind"] == "skin"
    assert accepted.artifact["trade_id"] == "9393511289"
    row = await _row(db_session)
    assert row.release_date == release
    assert row.accepted_at is not None


async def test_an_offer_not_accepted_fails_with_the_money_back(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-declined")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    task = await _task(db_session, item)
    failed = await skin_status(
        _Client(trades=[_trade(6, reason="Buyer failed to accept")]), db=db_session, task=task
    )
    assert (failed.outcome, failed.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert failed.error == "not_accepted"
    assert (await _row(db_session)).reason == "Buyer failed to accept"


async def test_an_unconfirmed_buy_that_never_shows_up_is_unknown_after_10_minutes(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-ghost")
    old = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    task = await _task(db_session, item, buy_unconfirmed_at=old)
    status = await skin_status(_Client(trades=[]), db=db_session, task=task)
    assert (status.outcome, status.money_outcome) == ("failed", MoneyOutcome.UNKNOWN)


async def test_the_waxpeer_fulfiller_routes_skin_lines_and_tasks(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.fulfillment.suppliers import waxpeer as wx
    from yupay.modules.integrations.models import SkuSupplierMapping

    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    from yupay.core import config as cfg

    cfg.get_settings.cache_clear()
    item = await _item(db_session, "sk-route")
    db_session.add(
        SkuSupplierMapping(
            sku_id=item.sku_id, supplier_slug="waxpeer", kind="skin", external_product_id="x"
        )
    )
    await db_session.commit()
    seen: list[str] = []

    async def fake_fulfill(client: object, **kw: Any) -> Any:
        seen.append("fulfill")
        return _failed_result()

    async def fake_status(client: object, **kw: Any) -> Any:
        seen.append("status")
        return _failed_status()

    monkeypatch.setattr(wx, "fulfill_skin", fake_fulfill)
    monkeypatch.setattr(wx, "skin_status", fake_status)
    ff = wx.WaxpeerFulfiller()
    order = item.order_id
    await ff.fulfill(db=db_session, order=order, item=item, idempotency_key=KEY)  # type: ignore[arg-type]
    task = await _task(db_session, item)
    await ff.check_status(db=db_session, task=task)
    assert seen == ["fulfill", "status"]
    cfg.get_settings.cache_clear()


def _failed_result() -> Any:
    from yupay.modules.fulfillment.suppliers.base import FulfillResult

    return FulfillResult(
        outcome="in_progress",
        external_order_id=KEY,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={},
        money_outcome=None,
    )


def _failed_status() -> Any:
    from yupay.modules.fulfillment.suppliers.base import FulfillStatus

    return FulfillStatus(
        outcome="in_progress", artifact_kind=None, artifact=None, error=None, money_outcome=None
    )
