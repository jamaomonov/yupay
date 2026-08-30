"""``start_for_order``'s plan/execute split behind ``fulfilment_async``.

Off (the default), ``start_for_order`` still walks a paid order straight
through to ``delivered`` in-process, byte-identical to today. On, it plans
(creates the ``fulfillment_tasks`` rows, flips the order to ``fulfilling``)
but leaves every task ``pending`` and rides a ``pg_notify('fulfillment_queue',
...)`` on the caller's own transaction instead of executing anything — the
rows in ``fulfillment_tasks`` *are* the queue, and Postgres delivers the
NOTIFY on COMMIT and drops it on ROLLBACK for free.

The order/SKU factory below mirrors ``test_fulfillment_service_paths.py``'s
``_seed_unit`` in shape, but builds the ``Order``/``OrderItem`` rows directly
via the ORM (like ``test_admin_fulfillment_bulk_routes.py``'s ``_make_task``)
rather than through checkout + the payment webhook — going through the
webhook would call ``start_for_order`` itself (``payments/service.py``) before
this file gets a chance to call it with an injected ``settings``, leaving no
``pending`` tasks to observe.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.suppliers.mock import MockFulfiller
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


def _settings(**overrides: object) -> Settings:
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings(**base)


def _database_dsn(settings: Settings) -> str:
    """asyncpg wants a bare ``postgresql://`` DSN, not SQLAlchemy's
    ``+asyncpg`` driver suffix. Task 3's consumer needs the same conversion
    in prod code.
    """
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _make_paid_order(db: AsyncSession, *, tag: str) -> Order:
    """Build a catalog chain + a ``paid`` order directly via the ORM and
    commit it — no checkout, no payment webhook, so ``start_for_order``
    has not run yet and the test controls exactly when it does.

    ``kind="voucher"`` with no supplier mapping and no inventory stock
    resolves to inventory -> ``mock`` fallback (``sourcing._resolve_auto``),
    which is what lets the flag-off test reach ``delivered`` synchronously
    from these same fixtures.
    """
    user_id = new_id()
    db.add(
        User(
            id=user_id,
            email=f"async-{tag}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()

    category = Category(id=new_id(), slug=f"cat-async-{tag}")
    db.add(category)
    await db.flush()
    brand = Brand(id=new_id(), slug=f"brand-async-{tag}", category_id=category.id)
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug=f"product-async-{tag}", brand_id=brand.id, kind="voucher")
    db.add(product)
    await db.flush()
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-async-{tag}",
        price_usd=Decimal("1.00"),
    )
    db.add(sku)
    await db.flush()

    order = Order(
        id=new_id(),
        user_id=user_id,
        status="paid",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku.id,
            qty=1,
            unit_price_usd=Decimal("1.00"),
        )
    )
    await db.commit()
    return order


# ---------- flag on: plan, don't execute ----------


async def test_flag_on_plans_but_does_not_execute(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tasks land `pending` in the caller's transaction; no supplier runs."""

    async def _must_not_be_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("MockFulfiller.fulfill must not run with fulfilment_async on")

    monkeypatch.setattr(MockFulfiller, "fulfill", _must_not_be_called)

    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session, tag="on")
    tasks = await ff_svc.start_for_order(db_session, order_id=order.id, settings=cfg)

    assert tasks
    assert [t.status for t in tasks] == ["pending"] * len(tasks)
    refreshed = await db_session.get(Order, order.id)
    assert refreshed is not None
    assert refreshed.status == "fulfilling"  # planning happened


# ---------- NOTIFY rides the transaction ----------


async def test_notify_rides_the_transaction(db_session: AsyncSession) -> None:
    """pg_notify is delivered on COMMIT and dropped on ROLLBACK — the
    property the whole design leans on, asserted against a real listener.
    """
    dsn = _database_dsn(get_settings())
    conn = await asyncpg.connect(dsn)
    heard: list[str] = []
    await conn.add_listener("fulfillment_queue", lambda *a: heard.append(a[-1]))
    try:
        cfg = _settings(fulfilment_async=True)

        order1 = await _make_paid_order(db_session, tag="rollback")
        order1_id = order1.id  # captured before rollback expires the attribute
        await ff_svc.start_for_order(db_session, order_id=order1_id, settings=cfg)
        await db_session.rollback()
        await asyncio.sleep(0.2)
        # Scoped to what this test sent — an earlier test's listener isn't
        # this one, but a NOTIFY sent before this listener attached could in
        # principle still be pending delivery; assert on payload, not count.
        assert order1_id not in heard  # rollback -> silence

        order2 = await _make_paid_order(db_session, tag="commit")
        order2_id = order2.id
        await ff_svc.start_for_order(db_session, order_id=order2_id, settings=cfg)
        await db_session.commit()
        await asyncio.sleep(0.2)
        assert order2_id in heard  # commit -> delivered
    finally:
        await conn.close()


# ---------- flag off: unchanged behaviour ----------


async def test_flag_off_is_todays_behaviour(db_session: AsyncSession) -> None:
    """With the default settings the order walks straight to delivered —
    the same assertion the sync suite makes, from this file's fixtures.
    """
    order = await _make_paid_order(db_session, tag="off")
    await ff_svc.start_for_order(db_session, order_id=order.id)
    refreshed = await db_session.get(Order, order.id)
    assert refreshed is not None
    assert refreshed.status in ("fulfilled", "delivered")
