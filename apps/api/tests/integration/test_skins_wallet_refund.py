"""A failed skin purchase refunds itself to the customer's YuPay balance (plan 3a, Task 7)."""

from __future__ import annotations

from decimal import Decimal
from types import ModuleType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.wallet import service as wallet

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


def _payments() -> ModuleType:
    # Lazy: payments.service <-> wallet.api <-> api.v1 is a known import cycle.
    from yupay.modules.payments import service

    return service


AMOUNT = Decimal("385700")


async def _paid(db: AsyncSession, tag: str, *, provider: str = "click") -> tuple[Order, Payment]:
    order = await _make_paid_order(db, tag=tag)
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider=provider,
        status="succeeded",
        amount=AMOUNT,
        currency="UZS",
        extra_metadata={},
    )
    db.add(payment)
    await db.commit()
    return order, payment


async def _balance(db: AsyncSession, user_id: str) -> Decimal:
    acc = await wallet.ensure_account(
        db, owner_type="user", owner_id=user_id, kind="user_wallet", currency="UZS"
    )
    return await wallet.balance(db, acc.id)


async def test_a_card_paid_order_comes_back_as_balance(db_session: AsyncSession) -> None:
    order, payment = await _paid(db_session, "rw-card")
    user_id = order.user_id
    assert user_id is not None
    assert await _payments().refund_order_to_wallet(
        db_session, order_id=order.id, reason="not_accepted"
    )
    await db_session.commit()
    assert await _balance(db_session, user_id) == AMOUNT
    await db_session.refresh(payment)
    await db_session.refresh(order)
    assert payment.status == "refunded"
    assert payment.extra_metadata["last_refund"]["refunded_to"] == "wallet"
    assert order.status == "refunded"


async def test_a_wallet_paid_order_goes_back_to_the_wallet(db_session: AsyncSession) -> None:
    order, _ = await _paid(db_session, "rw-wallet", provider="wallet")
    user_id = order.user_id
    assert user_id is not None
    await _payments().refund_order_to_wallet(db_session, order_id=order.id, reason="sold_out")
    await db_session.commit()
    assert await _balance(db_session, user_id) == AMOUNT


async def test_a_second_trigger_refunds_nothing_more(db_session: AsyncSession) -> None:
    order, _ = await _paid(db_session, "rw-twice")
    user_id = order.user_id
    assert user_id is not None
    assert await _payments().refund_order_to_wallet(db_session, order_id=order.id, reason="x")
    await db_session.commit()
    assert not await _payments().refund_order_to_wallet(db_session, order_id=order.id, reason="x")
    await db_session.commit()
    assert await _balance(db_session, user_id) == AMOUNT


async def test_an_admin_refund_after_it_is_refused(db_session: AsyncSession) -> None:
    order, payment = await _paid(db_session, "rw-admin")
    await _payments().refund_order_to_wallet(db_session, order_id=order.id, reason="x")
    await db_session.commit()
    with pytest.raises(ConflictError):
        await _payments().refund_admin(db_session, payment_id=payment.id, admin_id=new_id())


async def _failed_skin_task(db: AsyncSession, order: Order, money: MoneyOutcome) -> str:
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="failed",
        extra_metadata={"waxpeer_kind": "skin", "money_outcome": money.value},
    )
    db.add(task)
    await db.commit()
    return task.id


async def test_a_skin_task_that_failed_with_the_money_back_refunds_the_customer(
    db_session: AsyncSession,
) -> None:
    order, _ = await _paid(db_session, "rw-hook")
    user_id = order.user_id
    assert user_id is not None
    task_id = await _failed_skin_task(db_session, order, MoneyOutcome.RETURNED)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert await _balance(db_session, user_id) == AMOUNT


async def test_an_unknown_outcome_refunds_nothing(db_session: AsyncSession) -> None:
    order, _ = await _paid(db_session, "rw-unknown")
    user_id = order.user_id
    assert user_id is not None
    task_id = await _failed_skin_task(db_session, order, MoneyOutcome.UNKNOWN)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    assert await _balance(db_session, user_id) == Decimal("0")


async def test_a_declined_offer_seen_by_the_sweep_lands_on_the_balance(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    import respx
    from yupay.core import config as cfg
    from yupay.modules.skins.models import SkinTrade

    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    monkeypatch.setenv("WAXPEER_BASE_URL", "https://api.waxpeer.test/v1")
    cfg.get_settings.cache_clear()
    order, _ = await _paid(db_session, "rw-e2e")
    user_id = order.user_id
    assert user_id is not None
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalar_one()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="in_progress",
        external_order_id="key-rw-e2e",
        extra_metadata={"waxpeer_kind": "skin"},
    )
    db_session.add(task)
    db_session.add(
        SkinTrade(
            id=new_id(),
            order_item_id=item.id,
            project_id="key-rw-e2e",
            listing_id=1,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            paid_units=27867,
            status=4,
        )
    )
    await db_session.commit()
    declined = {
        "id": 1,
        "project_id": "key-rw-e2e",
        "status": 6,
        "done": True,
        "reason": "Buyer failed to accept",
        "price": 27867,
    }
    with respx.mock:
        respx.get("https://api.waxpeer.test/v1/check-many-project-id").mock(
            return_value=httpx.Response(200, json={"success": True, "trades": [declined]})
        )
        await ff_svc.process_webhook_update(db_session, task_id=task.id)
        await db_session.commit()
    cfg.get_settings.cache_clear()
    assert await _balance(db_session, user_id) == AMOUNT


async def test_a_skin_low_balance_ends_the_line_and_alerts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.fulfillment.suppliers.base import FulfillResult

    alerts: list[str] = []

    def _capture(coro: object) -> None:
        alerts.append(getattr(coro, "__qualname__", ""))
        coro.close()  # type: ignore[attr-defined] # a coroutine; never run in a unit test

    monkeypatch.setattr(ff_svc, "_dispatch_alert", _capture)
    order, _ = await _paid(db_session, "rw-lowbal")
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalar_one()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="in_progress",
        extra_metadata={"waxpeer_kind": "skin"},
    )
    result = FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error="supplier_low_balance",
        extra_metadata={"waxpeer_kind": "skin", "required_units": 27867},
        money_outcome=MoneyOutcome.RETURNED,
    )
    ff_svc._apply_failure(task=task, item=item, result=result)
    assert item.fulfillment_state == "failed"
    assert (task.extra_metadata or {})["money_outcome"] == MoneyOutcome.RETURNED.value
    assert alerts == ["_alert_skin_low_balance"]


async def test_a_retry_after_the_refund_is_refused(db_session: AsyncSession) -> None:
    # Retrying a refunded skin would buy it on our money: the customer has it back.
    order, _ = await _paid(db_session, "rw-retry")
    task_id = await _failed_skin_task(db_session, order, MoneyOutcome.RETURNED)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    with pytest.raises(ConflictError):
        await ff_svc.retry_task(db_session, task_id=task_id)


async def test_the_refund_is_pushed_to_the_open_page_and_the_bot(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.notifications import api as notifications
    from yupay.modules.realtime import api as realtime

    pushed: list[tuple[str | None, dict[str, object]]] = []
    scheduled: list[object] = []

    async def _publish(user_id: str | None, message: dict[str, object]) -> None:
        pushed.append((user_id, message))

    def _schedule(_db: object, factory: object) -> None:
        scheduled.append(factory)

    async def _no_bot(_order_id: str, *, try_later: bool = False) -> bool:
        return True

    monkeypatch.setattr(realtime, "publish_order_event", _publish)
    monkeypatch.setattr(notifications, "schedule_after_commit", _schedule)
    order, _ = await _paid(db_session, "rw-push")
    task_id = await _failed_skin_task(db_session, order, MoneyOutcome.RETURNED)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()
    # Nothing is pushed until the refund is committed; then the page and the bot hear it.
    assert [m for _, m in pushed if m.get("type") == "order.refunded"] == []
    assert len(scheduled) == 1
    monkeypatch.setattr(notifications, "notify_skin_refunded", _no_bot)
    await scheduled[0]()  # type: ignore[operator] # the scheduled zero-arg coroutine factory
    refunded = [m for _, m in pushed if m.get("type") == "order.refunded"]
    assert refunded == [{"type": "order.refunded", "orderId": order.id, "to": "wallet"}]
    assert [u for u, m in pushed if m.get("type") == "order.refunded"] == [order.user_id]
    assert len(scheduled) == 1


async def test_a_replayed_refund_pushes_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.notifications import api as notifications
    from yupay.modules.realtime import api as realtime

    # The first refund's own after-commit notice is not what this test is about.
    monkeypatch.setattr(notifications, "schedule_after_commit", lambda *_: None)
    order, _ = await _paid(db_session, "rw-push2")
    task_id = await _failed_skin_task(db_session, order, MoneyOutcome.RETURNED)
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    await db_session.commit()

    pushed: list[dict[str, object]] = []

    async def _publish(_user_id: str | None, message: dict[str, object]) -> None:
        pushed.append(message)

    monkeypatch.setattr(realtime, "publish_order_event", _publish)
    monkeypatch.setattr(notifications, "schedule_after_commit", lambda *_: pushed.append({}))
    await ff_svc._settle_merchant_deposit(db_session, task_id=task_id)
    assert pushed == []
