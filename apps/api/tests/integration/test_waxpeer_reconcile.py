"""Integration tests for the Waxpeer reconciliation sweep (Task 12).

Waxpeer has no webhook: a top-up that comes back ``created``/``sending``
from ``fulfill()`` would sit ``in_progress`` forever without something to
drive it to a terminal state. These tests exercise
``yupay_scheduler.jobs.waxpeer_reconcile.run_waxpeer_reconcile`` end to end
against a directly-seeded ``FulfillmentTask`` + stubbed Waxpeer HTTP —
mirroring how ``tests/contract/test_waxpeer_fulfiller.py`` stubs
``check_status`` at the fulfiller layer, one level up.

The job builds its own session via ``get_session_factory()`` (never a
request-scoped session) — see ``apps/scheduler/.../jobs/expire_orders.py``.
``_job_session_factory`` below redirects that call at the *job module*, the
same way ``test_seed_catalog.py`` redirects ``seed_catalog.get_session_factory``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

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
from yupay.modules.fulfillment.models import Delivery, FulfillmentAttempt, FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay_scheduler.jobs import waxpeer_reconcile

pytestmark = pytest.mark.asyncio

BASE = "https://waxpeer.reconcile.test/v1"
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
    monkeypatch.setattr(waxpeer_reconcile, "get_session_factory", lambda: factory)


# ---------- fixtures: seed a task without going through checkout ----------


def _topup_json(
    *,
    topup_id: int = 1,
    custom_id: str,
    status: str,
    amount: int = 10000,
    give_amount: int | None = None,
    steam_login: str = "gaben",
) -> dict[str, object]:
    return {
        "success": True,
        "topup": {
            "id": topup_id,
            "custom_id": custom_id,
            "status": status,
            "amount": amount,
            "give_amount": give_amount if give_amount is not None else amount,
            "steam_login": steam_login,
        },
    }


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
        fulfillment_data={"steam_login": "gaben"},
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


# ---------- the four required cases ----------


@respx.mock
async def test_sweep_completes_a_credited_topup(db_session: AsyncSession) -> None:
    """An in_progress waxpeer task whose Waxpeer status is now `completed`
    reaches `delivered` after one sweep."""
    task = await _seed_task(
        db_session,
        tag="credited",
        supplier="waxpeer",
        task_status="in_progress",
        external_order_id="custom-credited",
    )
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json=_topup_json(
                custom_id="custom-credited", status="completed", amount=10000, give_amount=10000
            ),
        )
    )

    await waxpeer_reconcile.run_waxpeer_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "succeeded"
    assert updated.last_error is None

    item = await _reload_item(db_session, task.order_item_id)
    assert item.fulfillment_state == "delivered"

    order = await _reload_order(db_session, task.order_id)
    assert order.status == "delivered"

    delivery = (
        await db_session.execute(select(Delivery).where(Delivery.order_item_id == item.id))
    ).scalar_one()
    assert delivery.artifact_kind == "topup_receipt"
    assert delivery.artifact["source"] == "waxpeer"


@respx.mock
async def test_sweep_flags_an_errored_topup_for_reconciliation(db_session: AsyncSession) -> None:
    """status=error ⇒ task failed, needs_reconciliation surfaced via
    last_error, not silently left in_progress."""
    task = await _seed_task(
        db_session,
        tag="errored",
        supplier="waxpeer",
        task_status="in_progress",
        external_order_id="custom-errored",
    )
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(custom_id="custom-errored", status="error")
        )
    )

    await waxpeer_reconcile.run_waxpeer_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "failed"
    assert updated.last_error is not None
    assert "reconcil" in updated.last_error.lower()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.fulfillment_state == "failed"

    order = await _reload_order(db_session, task.order_id)
    assert order.status != "delivered"

    attempts = await _attempts_for(db_session, task.id)
    assert any(a.kind == "status_check" and a.status == "error" for a in attempts)


@respx.mock
async def test_sweep_leaves_a_still_in_flight_topup_alone(db_session: AsyncSession) -> None:
    """status still `sending` ⇒ task stays in_progress, picked up next sweep."""
    task = await _seed_task(
        db_session,
        tag="inflight",
        supplier="waxpeer",
        task_status="in_progress",
        external_order_id="custom-inflight",
    )
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(custom_id="custom-inflight", status="sending")
        )
    )

    await waxpeer_reconcile.run_waxpeer_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "in_progress"

    item = await _reload_item(db_session, task.order_item_id)
    assert item.fulfillment_state == "in_progress"

    order = await _reload_order(db_session, task.order_id)
    assert order.status == "fulfilling"


@respx.mock
async def test_sweep_ignores_other_suppliers(db_session: AsyncSession) -> None:
    """A g2b in_progress task is not touched by the waxpeer sweep -- no HTTP
    call is even attempted for it (the empty respx registry would raise if
    one were), it stays in_progress, and no status_check attempt is recorded."""
    task = await _seed_task(
        db_session,
        tag="g2b-ignore",
        supplier="g2b",
        task_status="in_progress",
        external_order_id="g2b-order-1",
    )

    await waxpeer_reconcile.run_waxpeer_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "in_progress"
    assert await _attempts_for(db_session, task.id) == []


# ---------- extra coverage: pagination + double-sweep idempotency ----------


def _dynamic_topup_responder(
    statuses: dict[str, str],
) -> Callable[[httpx.Request], httpx.Response]:
    def _respond(request: httpx.Request) -> httpx.Response:
        custom_id = request.url.params.get("custom_id", "")
        status = statuses.get(custom_id, "completed")
        return httpx.Response(200, json=_topup_json(custom_id=custom_id, status=status))

    return _respond


@respx.mock
async def test_sweep_pages_through_more_than_one_page(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three stuck tasks with a page size of two must all get reconciled in
    one sweep -- the job pages instead of silently only handling page one."""
    monkeypatch.setattr(waxpeer_reconcile, "_PAGE_SIZE", 2)

    tasks = [
        await _seed_task(
            db_session,
            tag=f"page-{i}",
            supplier="waxpeer",
            task_status="in_progress",
            external_order_id=f"custom-page-{i}",
        )
        for i in range(3)
    ]
    statuses = {f"custom-page-{i}": "completed" for i in range(3)}
    respx.get(f"{BASE}/steam-topup").mock(side_effect=_dynamic_topup_responder(statuses))

    await waxpeer_reconcile.run_waxpeer_reconcile()

    for task in tasks:
        updated = await _reload_task(db_session, task.id)
        assert updated.status == "succeeded", task.id


@respx.mock
async def test_sweep_is_idempotent_under_a_double_sweep(db_session: AsyncSession) -> None:
    """A second, back-to-back sweep over an already-reconciled task must be a
    harmless no-op: process_webhook_update short-circuits terminal tasks, and
    because the task no longer matches status=in_progress the second sweep's
    own listing query does not even pick it up again."""
    task = await _seed_task(
        db_session,
        tag="double-sweep",
        supplier="waxpeer",
        task_status="in_progress",
        external_order_id="custom-double",
    )
    route = respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(custom_id="custom-double", status="completed")
        )
    )

    await waxpeer_reconcile.run_waxpeer_reconcile()
    first = await _reload_task(db_session, task.id)
    assert first.status == "succeeded"
    assert route.call_count == 1

    # Second sweep: nothing should change, and no second HTTP call is made
    # because the task no longer shows up as in_progress/waxpeer.
    await waxpeer_reconcile.run_waxpeer_reconcile()
    second = await _reload_task(db_session, task.id)
    assert second.status == "succeeded"
    assert second.succeeded_at == first.succeeded_at
    assert route.call_count == 1

    deliveries = (
        (
            await db_session.execute(
                select(Delivery).where(Delivery.order_item_id == task.order_item_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(deliveries) == 1
