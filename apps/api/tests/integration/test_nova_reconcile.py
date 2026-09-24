"""Integration tests for the NOVA reconciliation sweep (Task 3).

NOVA has no webhook: an order is charged at create and then sits in
``processing`` until it completes or is refunded, so without a poll a
finished order is never noticed. These tests exercise
``yupay_scheduler.jobs.nova_reconcile.run_nova_reconcile`` end to end against
a directly-seeded ``FulfillmentTask`` + stubbed NOVA HTTP — mirroring how
``test_waxpeer_reconcile.py`` and ``test_gengine_reconcile.py`` stub the same
supplier-generic reconciler, one level up from the fulfiller's own unit tests.

The job builds its own session via ``get_session_factory()`` (never a
request-scoped session) — see ``apps/scheduler/.../jobs/expire_orders.py``.
``_job_session_factory`` below redirects that call at the *job module*, the
same way the G-Engine and Waxpeer reconcile tests do for their own jobs.
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
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay_scheduler.jobs import nova_reconcile, panel_reconcile

# The sweep itself lives in ``panel_reconcile`` (NOVA and FazerCards are one
# protocol, ADR-0092); ``nova_reconcile`` is the binding that names the vendor.
# So the entry point is patched through the binding and the internals through
# the shared module — patching the binding for both would silently no-op.

# Import the app so every module is loaded before the delivery path reaches for
# them. Without it this file passes in a full run and fails on its own: the
# success branch lazily imports `auth.deps` mid-cycle and gets a partially
# initialised module. `test_gengine_reconcile.py` has the same latent problem
# and simply never runs alone.
import yupay.main  # noqa: F401  isort:skip

pytestmark = pytest.mark.asyncio

BASE = "https://nova.reconcile.test"
API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _nova_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_API_KEY", API_KEY)
    monkeypatch.setenv("NOVA_BASE_URL", BASE)
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
    monkeypatch.setattr(panel_reconcile, "get_session_factory", lambda: factory)


# ---------- fixtures: seed a task without going through checkout ----------


def _order_json(order_id: str, status: str) -> dict[str, Any]:
    """A NOVA order response exactly as ``GET /api/v2/orders/{id}`` returns."""
    return {"ok": True, "order": {"id": order_id, "status": status}}


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
    # that FK-references it, matching the seeding convention used across the
    # other reconcile tests.
    await db.flush()
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=unit_price_usd,
        fulfillment_data={"player_id": "1313232551"},
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


# ---------- the sweep's required behaviour ----------


@respx.mock
async def test_the_sweep_completes_a_finished_topup(db_session: AsyncSession) -> None:
    """An in_progress nova task whose order now reads `completed` is swept to
    `succeeded` -- and the order/item along with it. Nothing here pays: NOVA
    already took the money at create time, so this tick is a pure read."""
    task = await _seed_task(
        db_session,
        tag="completed",
        supplier="nova",
        task_status="in_progress",
        external_order_id="nv-completed",
    )
    order_route = respx.get(f"{BASE}/api/v2/orders/nv-completed").mock(
        return_value=httpx.Response(200, json=_order_json("nv-completed", "completed"))
    )

    await nova_reconcile.run_nova_reconcile()

    assert order_route.called, "the sweep must poll -- nothing else will"
    updated = await _reload_task(db_session, task.id)
    assert updated.status == "succeeded"
    assert updated.last_error is None

    item = await _reload_item(db_session, task.order_item_id)
    assert item.fulfillment_state == "delivered"

    order = await _reload_order(db_session, task.order_id)
    assert order.status == "delivered"


@respx.mock
async def test_the_sweep_leaves_a_still_processing_topup_alone(db_session: AsyncSession) -> None:
    """status still `processing` -- the ordinary case for most ticks -- leaves
    the task in_progress, to be picked up again on the next sweep."""
    task = await _seed_task(
        db_session,
        tag="processing",
        supplier="nova",
        task_status="in_progress",
        external_order_id="nv-processing",
    )
    respx.get(f"{BASE}/api/v2/orders/nv-processing").mock(
        return_value=httpx.Response(200, json=_order_json("nv-processing", "processing"))
    )

    await nova_reconcile.run_nova_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "in_progress"

    item = await _reload_item(db_session, task.order_item_id)
    assert item.fulfillment_state == "in_progress"

    order = await _reload_order(db_session, task.order_id)
    assert order.status == "fulfilling"


@respx.mock
async def test_a_task_that_raises_does_not_stop_the_sweep_of_the_next_one(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad row must never abort the batch. ``good`` is seeded first so it
    sorts *after* ``bad`` in the sweep's newest-first listing -- if the
    per-task isolation in ``run_nova_reconcile`` were missing, ``bad``'s
    exception would abort the tick before ``good`` is ever reached, and this
    assertion would catch that regression regardless of what the isolation
    bug actually looks like in production."""
    good = await _seed_task(
        db_session,
        tag="good",
        supplier="nova",
        task_status="in_progress",
        external_order_id="nv-good",
    )
    bad = await _seed_task(
        db_session,
        tag="bad",
        supplier="nova",
        task_status="in_progress",
        external_order_id="nv-bad",
    )
    respx.get(f"{BASE}/api/v2/orders/nv-good").mock(
        return_value=httpx.Response(200, json=_order_json("nv-good", "completed"))
    )

    real_process_webhook_update = ff_svc.process_webhook_update

    async def _flaky(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
        if task_id == bad.id:
            raise RuntimeError("simulated bad row")
        return await real_process_webhook_update(db, task_id=task_id)

    monkeypatch.setattr(panel_reconcile, "process_webhook_update", _flaky)

    await nova_reconcile.run_nova_reconcile()

    updated_good = await _reload_task(db_session, good.id)
    assert updated_good.status == "succeeded", "the good task must still be swept"

    updated_bad = await _reload_task(db_session, bad.id)
    assert updated_bad.status == "in_progress", "the bad task is skipped, not corrupted"


@respx.mock
async def test_the_sweep_leaves_other_suppliers_alone(db_session: AsyncSession) -> None:
    task = await _seed_task(
        db_session,
        tag="notours",
        supplier="g2b",
        task_status="in_progress",
        external_order_id="g2b-order-1",
    )

    await nova_reconcile.run_nova_reconcile()

    assert (await _reload_task(db_session, task.id)).status == "in_progress"
