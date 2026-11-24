"""A task a supplier refused moves once to the next cheapest one (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment import auto_failover
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.sourcing.models import SourcingSettings

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _mock_is_the_alternative(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _options(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
        return {"options": [{"supplier": "mock", "cost_usdt": Decimal("0.90"), "stock": None}]}

    monkeypatch.setattr("yupay.modules.fulfillment.reassign_options.reassign_options", _options)


async def _mode(db: AsyncSession, mode: str) -> None:
    row = await db.get(SourcingSettings, 1)
    if row is None:
        row = SourcingSettings(id=1)
        db.add(row)
    row.failover_mode = mode
    await db.commit()


async def _refused(
    db: AsyncSession, tag: str, *, money: MoneyOutcome = MoneyOutcome.RETURNED
) -> tuple[Order, str]:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
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
    return order, task.id


async def _task(db: AsyncSession, task_id: str) -> FulfillmentTask:
    task = await db.get(FulfillmentTask, task_id, populate_existing=True)
    assert task is not None
    return task


async def test_a_refused_task_moves_and_delivers(db_session: AsyncSession) -> None:
    await _mode(db_session, "retail")
    order, task_id = await _refused(db_session, "afo-move")
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    task = await _task(db_session, task_id)
    # Switched and queued, not run where the refusal was noticed.
    assert task.supplier == "mock"
    assert task.status == "pending"
    assert task.extra_metadata[auto_failover.FAILOVER_KEY]["from"] == "fzr"
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()
    assert (await _task(db_session, task_id)).status == "succeeded"
    kinds = (
        (await db_session.execute(select(OrderEvent.kind).where(OrderEvent.order_id == order.id)))
        .scalars()
        .all()
    )
    assert auto_failover.EVENT_KIND in kinds


async def test_switched_off_nothing_moves(db_session: AsyncSession) -> None:
    await _mode(db_session, "off")
    _, task_id = await _refused(db_session, "afo-off")
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert (await _task(db_session, task_id)).supplier == "fzr"


async def test_an_unconfirmed_refusal_never_moves(db_session: AsyncSession) -> None:
    await _mode(db_session, "retail")
    _, task_id = await _refused(db_session, "afo-unknown", money=MoneyOutcome.UNKNOWN)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert (await _task(db_session, task_id)).supplier == "fzr"


async def test_a_one_time_pack_never_moves(db_session: AsyncSession) -> None:
    await _mode(db_session, "retail")
    order, task_id = await _refused(db_session, "afo-otp")
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalar_one()
    sku = await db_session.get(Sku, item.sku_id)
    assert sku is not None
    sku.one_time_pack = True
    await db_session.commit()
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert (await _task(db_session, task_id)).supplier == "fzr"


async def test_a_task_moves_only_once(db_session: AsyncSession) -> None:
    await _mode(db_session, "retail")
    _, task_id = await _refused(db_session, "afo-once")
    task = await _task(db_session, task_id)
    task.extra_metadata = {**task.extra_metadata, auto_failover.FAILOVER_KEY: {"from": "g2b"}}
    await db_session.commit()
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert (await _task(db_session, task_id)).supplier == "fzr"
