"""Integration tests for the G2B reconciliation sweep.

G2B sends a terminal-status webhook, but it fires once with a single retry and
a 10s timeout — a lost webhook strands a completed top-up in ``in_progress``
forever (the ``poll_g2b_task`` dramatiq actor is only ever kicked off *by* the
webhook, so it can't recover a lost one). ``g2b_reconcile`` is the periodic
safety net, mirroring ``waxpeer_reconcile``; these tests exercise
``run_g2b_reconcile`` end to end against a directly-seeded task + stubbed G2B
HTTP, in the **real wrapped** response shape (``{"success", "order": {...}}``).

Seeding + session-redirect mechanics mirror ``test_waxpeer_reconcile.py`` — the
job resolves its own ``get_session_factory()``; we point it at the test engine.
"""

from __future__ import annotations

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
from yupay.modules.fulfillment.models import Delivery, FulfillmentTask
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.orders.models import Order, OrderItem
from yupay_scheduler.jobs import g2b_reconcile

pytestmark = pytest.mark.asyncio

BASE = "https://g2b.reconcile.test/v1"
API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _g2b_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", API_KEY)
    monkeypatch.setenv("G2B_BASE_URL", BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """The job resolves its own factory via ``get_session_factory()`` in
    production; point that at the test container so the job and the test's
    assertion session share one database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(g2b_reconcile, "get_session_factory", lambda: factory)


def _order_status_json(*, order_id: int, status: str, message: str = "") -> dict[str, object]:
    """The real G2B ``games/order/status`` shape: order wrapped under ``order``."""
    return {
        "success": True,
        "order": {"order_id": order_id, "status": status, "message": message},
    }


async def _seed_game_sku(db: AsyncSession, *, tag: str) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{tag}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=tag)],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{tag}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name=tag)],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{tag}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[{"key": "player_id", "label": "Player ID", "type": "text"}],
        translations=[ProductTranslation(locale="ru", name=tag)],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{tag}",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.flush()
    db.add(
        SkuSupplierMapping(
            sku_id=sku.id,
            supplier_slug="g2b",
            kind="game",
            external_product_id="pubg_mobile",
            external_variant_id="60",
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db.flush()
    return sku.id


async def _seed_task(
    db: AsyncSession,
    *,
    tag: str,
    supplier: str,
    external_order_id: str | None,
    with_mapping: bool = True,
) -> FulfillmentTask:
    """Seed Order + OrderItem + FulfillmentTask directly (guest order so the
    delivered-notification fan-out short-circuits with no Telegram/email)."""
    if with_mapping:
        sku_id = await _seed_game_sku(db, tag=tag)
    else:
        # A bare SKU with no g2b mapping — used only by the other-supplier case,
        # which never reaches mapping resolution.
        cat = Category(
            id=new_id(),
            slug=f"cat-{tag}",
            sort_order=10,
            active=True,
            translations=[CategoryTranslation(locale="ru", name=tag)],
        )
        brand = Brand(
            id=new_id(),
            slug=f"brand-{tag}",
            category_id=cat.id,
            sort_order=10,
            active=True,
            translations=[BrandTranslation(locale="ru", name=tag)],
        )
        product = Product(
            id=new_id(),
            slug=f"product-{tag}",
            brand_id=brand.id,
            kind="top_up",
            sort_order=10,
            active=True,
            required_fields=[],
            translations=[ProductTranslation(locale="ru", name=tag)],
        )
        sku = Sku(
            id=new_id(),
            product_id=product.id,
            sku_code=f"sku-{tag}",
            denomination="60",
            region="WW",
            price_usd=Decimal("1.00"),
            sort_order=10,
            active=True,
        )
        db.add_all([cat, brand, product, sku])
        await db.flush()
        sku_id = sku.id

    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=f"{tag}@example.test",
        status="fulfilling",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        expires_at=now() + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=Decimal("1.00"),
        fulfillment_data={"player_id": "5679523421"},
        fulfillment_state="in_progress",
    )
    db.add(item)
    await db.flush()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier=supplier,
        status="in_progress",
        external_order_id=external_order_id,
    )
    db.add(task)
    await db.commit()
    return task


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


@respx.mock
async def test_sweep_completes_a_credited_topup(db_session: AsyncSession) -> None:
    """An in_progress g2b task whose G2B status is now COMPLETED (real wrapped
    shape) reaches delivered after one sweep — the exact prod scenario."""
    task = await _seed_task(db_session, tag="credited", supplier="g2b", external_order_id="1309981")
    respx.post(f"{BASE}/games/order/status").mock(
        return_value=httpx.Response(
            200, json=_order_status_json(order_id=1309981, status="COMPLETED", message="done")
        )
    )

    await g2b_reconcile.run_g2b_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "succeeded"

    order = await _reload_order(db_session, task.order_id)
    assert order.status == "delivered"

    delivery = (
        await db_session.execute(
            select(Delivery).where(Delivery.order_item_id == task.order_item_id)
        )
    ).scalar_one()
    assert delivery.artifact_kind == "topup_receipt"
    assert delivery.artifact["source"] == "g2b"


@respx.mock
async def test_sweep_leaves_a_still_processing_topup_alone(db_session: AsyncSession) -> None:
    """status PROCESSING ⇒ task stays in_progress for the next sweep."""
    task = await _seed_task(db_session, tag="inflight", supplier="g2b", external_order_id="2000001")
    respx.post(f"{BASE}/games/order/status").mock(
        return_value=httpx.Response(
            200, json=_order_status_json(order_id=2000001, status="PROCESSING")
        )
    )

    await g2b_reconcile.run_g2b_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "in_progress"
    order = await _reload_order(db_session, task.order_id)
    assert order.status == "fulfilling"


@respx.mock
async def test_sweep_fails_a_failed_topup(db_session: AsyncSession) -> None:
    """status FAILED ⇒ task failed (G2B auto-refunds the balance upstream)."""
    task = await _seed_task(db_session, tag="failed", supplier="g2b", external_order_id="2000002")
    respx.post(f"{BASE}/games/order/status").mock(
        return_value=httpx.Response(
            200, json=_order_status_json(order_id=2000002, status="FAILED", message="rejected")
        )
    )

    await g2b_reconcile.run_g2b_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "failed"
    order = await _reload_order(db_session, task.order_id)
    assert order.status != "delivered"


@respx.mock
async def test_sweep_ignores_other_suppliers(db_session: AsyncSession) -> None:
    """A waxpeer in_progress task is untouched by the g2b sweep — no HTTP call
    is attempted (the empty respx registry would raise if one were)."""
    task = await _seed_task(
        db_session,
        tag="wax-ignore",
        supplier="waxpeer",
        external_order_id="wax-1",
        with_mapping=False,
    )

    await g2b_reconcile.run_g2b_reconcile()

    updated = await _reload_task(db_session, task.id)
    assert updated.status == "in_progress"
