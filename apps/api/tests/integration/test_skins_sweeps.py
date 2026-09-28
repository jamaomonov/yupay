"""Skin trade sweeps (plan 3a, Task 6): which tasks the fast sweep owns, how soon it
looks again, and the hourly watch over trades in Steam's 7-day protection."""

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
from yupay.modules.fulfillment.skin_sweeps import (
    due_skin_task_ids,
    skin_recheck_seconds,
    watch_protected_trades,
)
from yupay.modules.fulfillment.suppliers.waxpeer_trades import WaxpeerTrade
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio

RELEASE = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)


async def _task(db: AsyncSession, tag: str, *, skin: bool, status: int | None = None) -> str:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="in_progress",
        external_order_id=f"key-{tag}",
        extra_metadata={"waxpeer_kind": "skin"} if skin else {},
    )
    db.add(task)
    if skin:
        db.add(
            SkinTrade(
                id=new_id(),
                order_item_id=item.id,
                task_id=task.id,
                project_id=f"key-{tag}",
                listing_id=1,
                market_hash_name="AK-47 | Redline (Field-Tested)",
                paid_units=27867,
                status=status,
            )
        )
    await db.commit()
    return task.id


async def test_the_fast_sweep_takes_only_skin_tasks(db_session: AsyncSession) -> None:
    skin = await _task(db_session, "sw-skin", skin=True)
    topup = await _task(db_session, "sw-topup", skin=False)
    due = await due_skin_task_ids(db_session)
    assert skin in due
    assert topup not in due


async def test_a_trade_being_bought_is_looked_at_sooner_than_a_sent_offer(
    db_session: AsyncSession,
) -> None:
    buying = await _task(db_session, "sw-buying", skin=True, status=2)
    sent = await _task(db_session, "sw-sent", skin=True, status=4)
    assert await skin_recheck_seconds(db_session, task_id=buying) == 5
    assert await skin_recheck_seconds(db_session, task_id=sent) == 10


def _trade(project_id: str, status: int, **over: Any) -> WaxpeerTrade:
    base = WaxpeerTrade(
        id=1,
        project_id=project_id,
        status=status,
        trade_id="9393511289",
        done=status in (5, 6),
        reason=None,
        release_date=RELEASE,
        is_released=status == 5,
        send_until=None,
        price_units=27867,
        penalties=None,
        seller={},
    )
    return replace(base, **over)


class _Client:
    def __init__(self, trades: list[WaxpeerTrade]) -> None:
        self.trades = trades
        self.asked: list[list[str]] = []

    async def check_project_ids(self, ids: Sequence[str]) -> list[WaxpeerTrade]:
        self.asked.append(list(ids))
        return [t for t in self.trades if t.project_id in ids]


async def _protected(db: AsyncSession, tag: str) -> SkinTrade:
    task_id = await _task(db, tag, skin=True, status=4)
    row = (await db.execute(select(SkinTrade).where(SkinTrade.task_id == task_id))).scalar_one()
    row.release_date = RELEASE
    row.accepted_at = RELEASE - timedelta(days=7)
    task = await db.get(FulfillmentTask, task_id)
    assert task is not None
    task.status = "succeeded"
    await db.commit()
    return row


async def test_a_released_trade_is_marked_released(db_session: AsyncSession) -> None:
    row = await _protected(db_session, "pw-released")
    alerts: list[str] = []

    async def alert(text: str) -> None:
        alerts.append(text)

    client = _Client([_trade(row.project_id, 5)])
    assert await watch_protected_trades(db_session, client, alert=alert) == 1
    await db_session.refresh(row)
    assert (row.status, row.is_released) == (5, True)
    assert alerts == []


async def test_a_rollback_alerts_and_is_recorded_on_the_task(db_session: AsyncSession) -> None:
    row = await _protected(db_session, "pw-rollback")
    alerts: list[str] = []

    async def alert(text: str) -> None:
        alerts.append(text)

    penalties = {"rollback_fee": 1000, "rollback_penalty": 500, "total_penalty": 1500}
    client = _Client([_trade(row.project_id, 6, penalties=penalties, reason="Trade rolled back")])
    await watch_protected_trades(db_session, client, alert=alert)
    await db_session.refresh(row)
    assert row.status == 6
    assert len(alerts) == 1
    assert "откат" in alerts[0].lower()
    task = await db_session.get(FulfillmentTask, row.task_id)
    assert task is not None
    await db_session.refresh(task)
    assert task.extra_metadata["skin_rollback"]["penalties"] == penalties


async def test_waxpeer_reconcile_leaves_skin_tasks_to_their_own_sweep(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yupay_scheduler.jobs import waxpeer_reconcile

    skin = await _task(db_session, "wr-skin", skin=True)
    topup = await _task(db_session, "wr-topup", skin=False)
    bind = db_session.bind
    monkeypatch.setattr(
        waxpeer_reconcile,
        "get_session_factory",
        lambda: async_sessionmaker(bind=bind, expire_on_commit=False),
    )
    listed = await waxpeer_reconcile._list_stuck_task_ids()
    assert topup in listed
    assert skin not in listed


@pytest.mark.usefixtures("db_engine")
async def test_the_fast_sweep_delivers_an_accepted_skin_end_to_end(
    db_session: AsyncSession, db_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    import respx
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yupay.core import config as cfg
    from yupay.modules.fulfillment.models import Delivery
    from yupay_scheduler.jobs import skins_trades_reconcile

    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    monkeypatch.setenv("WAXPEER_BASE_URL", "https://api.waxpeer.test/v1")
    cfg.get_settings.cache_clear()
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(skins_trades_reconcile, "get_session_factory", lambda: factory)
    task_id = await _task(db_session, "e2e", skin=True, status=4)
    trade = {
        "id": 1,
        "project_id": "key-e2e",
        "status": 4,
        "trade_id": "9393511289",
        "done": False,
        "release_date": "2026-10-05T16:00:00.000Z",
        "is_released": False,
        "price": 27867,
    }
    with respx.mock:
        respx.get("https://api.waxpeer.test/v1/check-many-project-id").mock(
            return_value=httpx.Response(200, json={"success": True, "trades": [trade]})
        )
        await skins_trades_reconcile.run_skins_trades_reconcile()
    cfg.get_settings.cache_clear()

    async with factory() as s:
        task = await s.get(FulfillmentTask, task_id)
        assert task is not None
        assert task.status == "succeeded"
        assert task.next_attempt_at is not None
        delivery = (
            await s.execute(select(Delivery).where(Delivery.order_item_id == task.order_item_id))
        ).scalar_one()
        assert delivery.artifact["kind"] == "skin"
