"""The sweep that keeps a G-Engine top-up moving.

G-Engine orders are not one step: they walk ``pending → verified → paid →
shipped``, and ``verified`` is the state that opens payment — so a poll here is
not an observation, it is the call that spends our money. Nothing upstream calls
back to trigger it.

The job did not exist when the adapter shipped. The first live Stars order sat
at ``verified`` for nine hours with one attempt on the clock, our balance
untouched, the customer watching "в обработке" — the order was fine, nobody was
asking about it. These tests are that incident, written down.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core import config as cfg
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentAttempt, FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.fulfillment.suppliers.gengine import PAY_REQUESTED_KEY
from yupay.modules.orders.models import Order, OrderItem
from yupay_scheduler.jobs import gengine_reconcile

# Import the app so every module is loaded before the delivery path reaches for
# them. Without it this file passes in a full run and fails on its own: the
# success branch lazily imports `auth.deps` mid-cycle and gets a partially
# initialised module. `test_waxpeer_reconcile.py` has the same latent problem
# and simply never runs alone.
import yupay.main  # noqa: F401  isort:skip

pytestmark = pytest.mark.asyncio

BASE = "https://gengine.reconcile.test/v2.1"
API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _waxpeer_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WAXPEER_API_KEY", API_KEY)
    monkeypatch.setenv("WAXPEER_BASE_URL", BASE)
    monkeypatch.setenv("WAXPEER_FEE_RATE", "0")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """The job never uses the request-scoped ``db_session`` fixture — in
    production it resolves its own factory via ``get_session_factory()``.
    Point that at the truncated test container so the job's sessions and the
    test's assertion session (``db_session``) see the same database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(gengine_reconcile, "get_session_factory", lambda: factory)


# ---------- fixtures: seed a task without going through checkout ----------


async def _seed_sku(db: AsyncSession, *, slug: str) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{slug}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=slug)],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{slug}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name=slug)],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{slug}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug)],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{slug}",
        denomination="10",
        region="WW",
        price_usd=Decimal("10.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.flush()
    return sku.id


async def _seed_task(
    db: AsyncSession,
    *,
    tag: str,
    supplier: str,
    task_status: str,
    external_order_id: str | None,
    unit_price_usd: Decimal = Decimal("10.00"),
) -> FulfillmentTask:
    """Seed an Order + OrderItem + FulfillmentTask directly, bypassing
    checkout/payment/sourcing entirely -- the sweep only cares about the
    task row and the item/order it points at.

    Guest order (``user_id=None``) so the post-settlement notification
    fan-out (``notify_order_delivered``) short-circuits at the chat-id
    lookup (no linked Telegram user) instead of trying to reach Telegram or
    send an email (``settings.web_base_url`` defaults to empty in tests).
    """
    sku_id = await _seed_sku(db, slug=tag)
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=f"{tag}@example.test",
        status="fulfilling",
        currency="USD",
        total_usd=unit_price_usd,
        total_charged=unit_price_usd,
        expires_at=now() + timedelta(hours=1),
    )
    db.add(order)
    # No ORM ``relationship()`` links Order/OrderItem to FulfillmentTask (only
    # plain FK columns), so the unit of work has no dependency info to order
    # these inserts by itself -- flush each parent before adding the child
    # that FK-references it, matching the seeding convention used in
    # test_admin_fulfillment_bulk_routes.py.
    await db.flush()
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=unit_price_usd,
        fulfillment_data={"username": "@durov"},
        fulfillment_state="in_progress",
    )
    db.add(item)
    await db.flush()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier=supplier,
        status=task_status,
        external_order_id=external_order_id,
    )
    db.add(task)
    await db.commit()
    return task


API_KEY = "gengine-test-key"


@pytest.fixture(autouse=True)
def _gengine_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENGINE_API_KEY", API_KEY)
    monkeypatch.setenv("GENGINE_BASE_URL", BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _order_json(order_id: int, uuid: str, status: str) -> dict[str, Any]:
    """A recharge order exactly as the live API returns one."""
    return {
        "id": order_id,
        "uuid": uuid,
        "status": status,
        "price": 0.7727,
        "currency": "Stars",
        "is_refunded": False,
    }


#: The job reconciles through its *own* session (a separate one from
#: ``db_session``), bound to the same engine. ``db_session`` already holds
#: the pre-sweep row in its identity map (from ``_seed_task``'s own insert)
#: and, with ``expire_on_commit=False``, a plain ``select()`` would return
#: that stale cached instance instead of what the job just wrote.
#: ``populate_existing`` forces every reload below to re-read off the DB.
_FRESH = {"populate_existing": True}


async def _reload_task(db: AsyncSession, task_id: str) -> FulfillmentTask:
    return (
        await db.execute(
            select(FulfillmentTask).where(FulfillmentTask.id == task_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def _reload_order(db: AsyncSession, order_id: str) -> Order:
    return (
        await db.execute(select(Order).where(Order.id == order_id).execution_options(**_FRESH))
    ).scalar_one()


async def _reload_item(db: AsyncSession, item_id: str) -> OrderItem:
    return (
        await db.execute(
            select(OrderItem).where(OrderItem.id == item_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def _attempts_for(db: AsyncSession, task_id: str) -> list[FulfillmentAttempt]:
    return list(
        (await db.execute(select(FulfillmentAttempt).where(FulfillmentAttempt.task_id == task_id)))
        .scalars()
        .all()
    )


# ---------- the incident ----------


@respx.mock
async def test_the_sweep_pays_a_verified_order_on_the_tick_after_it_banks_the_intent(
    db_session: AsyncSession,
) -> None:
    """The whole reason this job exists. `verified` is not a state that
    resolves itself — we are what moves it, and without a sweep the order sits
    there indefinitely while the customer waits.

    It now takes two ticks rather than one, and the extra 60 seconds is bought
    on purpose: the record that we are about to spend has to be committed by a
    transaction that does **not** spend. Writing it inside the paying tick puts
    it behind ``_record_attempt``, the metadata merge, ``_try_settle_order``'s
    blocking ``FOR UPDATE`` and the COMMIT — and this path has no crash net, so
    any abort in that window rolls the record back while the money stays gone.
    See ``gengine.PAY_REQUESTED_KEY``.
    """
    task = await _seed_task(
        db_session,
        tag="verified",
        supplier="gengine",
        task_status="in_progress",
        external_order_id="1721708",
    )
    respx.get(f"{BASE}/recharge/orders/1721708").mock(
        return_value=httpx.Response(200, json=_order_json(1721708, task.id, "verified"))
    )
    pay = respx.post(f"{BASE}/recharge/orders/1721708/pay").mock(
        return_value=httpx.Response(200, json=_order_json(1721708, task.id, "paid"))
    )

    await gengine_reconcile.run_gengine_reconcile()

    assert pay.call_count == 0, "the tick that banks the intent must spend nothing"
    banked = await _reload_task(db_session, task.id)
    assert banked.status == "in_progress"
    assert banked.extra_metadata[PAY_REQUESTED_KEY] is True

    await gengine_reconcile.run_gengine_reconcile()

    assert pay.call_count == 1, "a verified order must be paid by the sweep"
    updated = await _reload_task(db_session, task.id)
    # `paid` is not delivery: the supplier still has to hand the stars over.
    assert updated.status == "in_progress"
    assert updated.last_error is None


@respx.mock
async def test_the_sweep_does_not_pay_an_order_twice(db_session: AsyncSession) -> None:
    """Every tick sees the same task until it ships. Paying on each one would
    buy the top-up again, and a top-up cannot be un-bought."""
    task = await _seed_task(
        db_session,
        tag="alreadypaid",
        supplier="gengine",
        task_status="in_progress",
        external_order_id="1721709",
    )
    respx.get(f"{BASE}/recharge/orders/1721709").mock(
        return_value=httpx.Response(200, json=_order_json(1721709, task.id, "paid"))
    )
    pay = respx.post(f"{BASE}/recharge/orders/1721709/pay").mock(
        return_value=httpx.Response(200, json=_order_json(1721709, task.id, "paid"))
    )

    await gengine_reconcile.run_gengine_reconcile()

    assert not pay.called
    assert (await _reload_task(db_session, task.id)).status == "in_progress"


@respx.mock
async def test_the_sweep_completes_a_shipped_order(db_session: AsyncSession) -> None:
    task = await _seed_task(
        db_session,
        tag="shipped",
        supplier="gengine",
        task_status="in_progress",
        external_order_id="1721710",
    )
    respx.get(f"{BASE}/recharge/orders/1721710").mock(
        return_value=httpx.Response(200, json=_order_json(1721710, task.id, "shipped"))
    )

    await gengine_reconcile.run_gengine_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "succeeded"

    item = await _reload_item(db_session, task.order_item_id)
    assert item.fulfillment_state == "delivered"

    order = await _reload_order(db_session, task.order_id)
    assert order.status == "delivered"


@respx.mock
async def test_a_wrong_username_fails_the_task_rather_than_hanging(
    db_session: AsyncSession,
) -> None:
    """G-Engine catches this before our money moves, which is the point of the
    verification step. It is the customer's mistake, not an outage."""
    task = await _seed_task(
        db_session,
        tag="badaccount",
        supplier="gengine",
        task_status="in_progress",
        external_order_id="1721711",
    )
    respx.get(f"{BASE}/recharge/orders/1721711").mock(
        return_value=httpx.Response(200, json=_order_json(1721711, task.id, "invalid_account"))
    )

    await gengine_reconcile.run_gengine_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "failed"
    assert "invalid_account" in (updated.last_error or "")
    # No pay request ever went out for this task, so our balance is provably
    # whole and M3b may refund the merchant automatically.
    assert ff_svc.money_outcome_of(updated) is MoneyOutcome.RETURNED
    assert PAY_REQUESTED_KEY not in updated.extra_metadata


@respx.mock
async def test_a_paid_order_that_later_reports_a_bad_account_is_not_free(
    db_session: AsyncSession,
) -> None:
    """The one the breadcrumb exists for, across two real sweep ticks.

    Tick 1 pays a ``verified`` order; the pay returns 200 and the order goes
    ``paid``, which is ``in_progress`` — an exit that records **no money
    outcome at all**. Tick 2 then sees ``invalid_account``. Asking only
    "did *this* call pay?" answers no for every status but ``verified``, so
    without something durable on the task the sweep would answer ``RETURNED``
    and M3b would refund a top-up whose pay call returned 200.

    This is also the proof that ``extra_metadata`` survives the poll path: the
    breadcrumb is written by ``fulfill``/``check_status`` and merged by
    ``process_webhook_update``, and nothing between the ticks clears it.
    """
    task = await _seed_task(
        db_session,
        tag="paidthenbad",
        supplier="gengine",
        task_status="in_progress",
        external_order_id="1721712",
    )
    respx.get(f"{BASE}/recharge/orders/1721712").mock(
        return_value=httpx.Response(200, json=_order_json(1721712, task.id, "verified"))
    )
    pay = respx.post(f"{BASE}/recharge/orders/1721712/pay").mock(
        return_value=httpx.Response(200, json=_order_json(1721712, task.id, "paid"))
    )

    # Tick 1 banks the intent, tick 2 spends it. That split is what makes the
    # key durable: it is committed by a transaction that cannot have paid.
    await gengine_reconcile.run_gengine_reconcile()
    assert pay.call_count == 0
    await gengine_reconcile.run_gengine_reconcile()
    assert pay.call_count == 1

    after_pay = await _reload_task(db_session, task.id)
    assert after_pay.status == "in_progress"
    assert ff_svc.money_outcome_of(after_pay) is None, "nothing terminal happened yet"
    assert after_pay.extra_metadata[PAY_REQUESTED_KEY] is True

    respx.get(f"{BASE}/recharge/orders/1721712").mock(
        return_value=httpx.Response(200, json=_order_json(1721712, task.id, "invalid_account"))
    )

    await gengine_reconcile.run_gengine_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "failed"
    assert ff_svc.money_outcome_of(updated) is MoneyOutcome.UNKNOWN


@respx.mock
async def test_the_intent_survives_a_paying_tick_that_rolls_back(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the write and the spend are in different transactions.

    Tick 1 banks the intent and commits it. Tick 2 pays — and then dies before
    its own COMMIT, exactly as a deadlock victim, a statement timeout or a
    malformed pay response would. Everything tick 2 wrote is gone; the money
    is not. The intent has to be still on the row, because tick 3 is where the
    supplier says ``invalid_account`` and an unarmed task answers ``RETURNED``
    for a top-up we bought.

    ``run_gengine_reconcile`` only logs a failed task — unlike the drain, this
    path has no crash net to fall back on — which is what makes the ordering
    load-bearing rather than belt-and-braces.
    """
    task = await _seed_task(
        db_session,
        tag="rollback",
        supplier="gengine",
        task_status="in_progress",
        external_order_id="1721713",
    )
    respx.get(f"{BASE}/recharge/orders/1721713").mock(
        return_value=httpx.Response(200, json=_order_json(1721713, task.id, "verified"))
    )
    pay = respx.post(f"{BASE}/recharge/orders/1721713/pay").mock(
        return_value=httpx.Response(200, json=_order_json(1721713, task.id, "paid"))
    )

    await gengine_reconcile.run_gengine_reconcile()
    assert (await _reload_task(db_session, task.id)).extra_metadata[PAY_REQUESTED_KEY] is True

    async def _abort(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(ff_svc, "_try_settle_order", _abort)

    await gengine_reconcile.run_gengine_reconcile()

    assert pay.call_count == 1, "the money left on the tick that then died"
    monkeypatch.undo()

    survived = await _reload_task(db_session, task.id)
    assert survived.extra_metadata[PAY_REQUESTED_KEY] is True, "committed before the pay"

    respx.get(f"{BASE}/recharge/orders/1721713").mock(
        return_value=httpx.Response(200, json=_order_json(1721713, task.id, "invalid_account"))
    )

    await gengine_reconcile.run_gengine_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "failed"
    assert ff_svc.money_outcome_of(updated) is MoneyOutcome.UNKNOWN


@respx.mock
async def test_the_sweep_leaves_other_suppliers_alone(db_session: AsyncSession) -> None:
    task = await _seed_task(
        db_session,
        tag="notours",
        supplier="g2b",
        task_status="in_progress",
        external_order_id="1721712",
    )

    await gengine_reconcile.run_gengine_reconcile()

    assert (await _reload_task(db_session, task.id)).status == "in_progress"
