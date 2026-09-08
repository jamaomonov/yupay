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
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers import FulfillerError, FulfillResult, MoneyOutcome
from yupay.modules.fulfillment.suppliers.mock import MockFulfiller
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
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


async def _make_paid_order(db: AsyncSession, *, tag: str, n_items: int = 1) -> Order:
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
    for _ in range(n_items):
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
        # Postgres drops a NOTIFY outright when nobody is listening — it is
        # never queued for a listener that attaches later. Asserting on this
        # order's own id (not just an empty ``heard``) is what keeps the
        # check immune to any cross-test NOTIFY chatter on the same channel.
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


# ---------- drain_pending_tasks: claim-and-run ----------


@pytest.fixture
async def second_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A second session bound to the same (truncated) engine as ``db_session``.

    Stands in for a second worker replica racing the first over the same
    claim query — the concurrency proof needs two real connections, not a
    mocked lock.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_drain_processes_pending_to_delivery(db_session: AsyncSession) -> None:
    """A task left ``pending`` by the flag-on path gets claimed, run, and
    its order settled — the same terminal state the synchronous saga reaches.
    """
    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session, tag="drain")
    await ff_svc.start_for_order(db_session, order_id=order.id, settings=cfg)
    await db_session.commit()

    n = await ff_svc.drain_pending_tasks(db_session)

    assert n >= 1
    refreshed = await db_session.get(Order, order.id)
    assert refreshed is not None
    assert refreshed.status in ("fulfilled", "delivered")


async def test_drain_with_nothing_pending_is_a_noop(db_session: AsyncSession) -> None:
    assert await ff_svc.drain_pending_tasks(db_session) == 0


async def test_skip_locked_makes_duplicates_harmless(
    db_session: AsyncSession,
    second_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consumers race the same pending backlog: every task runs exactly
    once. This is the entire concurrency story, so it gets a real
    two-session proof rather than a mocked lock.
    """
    calls: dict[str, int] = {}
    original_fulfill = MockFulfiller.fulfill

    async def _counting_fulfill(
        self: MockFulfiller,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        calls[idempotency_key] = calls.get(idempotency_key, 0) + 1
        return await original_fulfill(
            self, db=db, order=order, item=item, idempotency_key=idempotency_key
        )

    monkeypatch.setattr(MockFulfiller, "fulfill", _counting_fulfill)

    cfg = _settings(fulfilment_async=True)
    order_a = await _make_paid_order(db_session, tag="race-a")
    order_b = await _make_paid_order(db_session, tag="race-b")
    await ff_svc.start_for_order(db_session, order_id=order_a.id, settings=cfg)
    await ff_svc.start_for_order(db_session, order_id=order_b.id, settings=cfg)
    await db_session.commit()

    ran = await asyncio.gather(
        ff_svc.drain_pending_tasks(db_session),
        ff_svc.drain_pending_tasks(second_session),
    )

    assert sum(ran) == 2  # one task per order, split any way between the two
    assert calls  # every task actually ran
    assert max(calls.values()) == 1  # and none of them ran twice


async def test_drain_isolates_a_poisoned_task(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unwrapped crash from one task's fulfiller — not a ``FulfillerError``,
    which ``process_task`` already handles — must not poison the whole
    batch: the crashed task lands ``failed`` (not stuck ``pending``, which
    would livelock the queue as the worker's rollback + re-tick reclaims it
    forever) and the rest of the batch still completes and settles.
    """
    cfg = _settings(fulfilment_async=True)
    poisoned_order = await _make_paid_order(db_session, tag="poison")
    healthy_order = await _make_paid_order(db_session, tag="healthy")
    await ff_svc.start_for_order(db_session, order_id=poisoned_order.id, settings=cfg)
    await ff_svc.start_for_order(db_session, order_id=healthy_order.id, settings=cfg)
    await db_session.commit()

    poisoned_task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == poisoned_order.id)
        )
    ).scalar_one()

    original_fulfill = MockFulfiller.fulfill

    async def _boom_for_one_task(
        self: MockFulfiller,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if idempotency_key == poisoned_task_id:
            raise RuntimeError("boom")
        return await original_fulfill(
            self, db=db, order=order, item=item, idempotency_key=idempotency_key
        )

    monkeypatch.setattr(MockFulfiller, "fulfill", _boom_for_one_task)

    n = await ff_svc.drain_pending_tasks(db_session)
    assert n == 2  # both claimed and attempted this tick

    poisoned_task = await db_session.get(FulfillmentTask, poisoned_task_id)
    assert poisoned_task is not None
    assert poisoned_task.status == "failed"
    assert poisoned_task.last_error is not None
    assert "boom" in poisoned_task.last_error

    healthy_task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == healthy_order.id)
        )
    ).scalar_one()
    assert healthy_task.status == "succeeded"

    refreshed_healthy_order = await db_session.get(Order, healthy_order.id)
    assert refreshed_healthy_order is not None
    assert refreshed_healthy_order.status in ("fulfilled", "delivered")

    # The poisoned row moved straight to 'failed' — a second tick must not
    # reclaim it (that would just crash again and spin forever). Commit first:
    # the real consumer commits between ticks, so non-reclaim must hold across
    # a commit boundary, not just via read-your-own-writes in one transaction.
    await db_session.commit()
    n2 = await ff_svc.drain_pending_tasks(db_session)
    assert n2 == 0


# ---------- admin mutations vs. a mid-flight consumer ----------


async def test_cancel_waits_for_a_claimed_task_and_never_overwrites_it(
    db_session: AsyncSession, second_session: AsyncSession
) -> None:
    """An admin cancel must not clobber a task the consumer is mid-flight on.

    The money-safety case: a refund cancels the order's open tasks while a
    drainer already holds the claim lock and is about to commit
    ``succeeded``. Without a lock on the cancel side, the cancel reads
    ``pending`` (its snapshot predates the consumer's commit), queues behind
    the row lock, and its UPDATE lands *after* the consumer's — refund issued
    AND goods delivered, with the row saying ``cancelled``.

    So: session A claims the row and marks it succeeded with its transaction
    still open; session B cancels the order's tasks concurrently. B must
    block until A commits, and must then leave the row ``succeeded``.
    """
    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session, tag="lockrace")
    await ff_svc.start_for_order(db_session, order_id=order.id, settings=cfg)
    await db_session.commit()

    # A: the consumer's claim (same FOR UPDATE the drain query takes), then
    # the success write -- flushed, so the row lock is held, not committed.
    claimed = (
        await second_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order.id).with_for_update()
        )
    ).scalar_one()
    claimed_id = claimed.id
    claimed.status = "succeeded"
    claimed.succeeded_at = datetime.now(UTC)
    await second_session.flush()

    # B: the admin/refund cascade, racing A.
    cancelling = asyncio.create_task(
        ff_svc.cancel_open_tasks_for_order(db_session, order_id=order.id, reason="refund:test")
    )
    done, _pending = await asyncio.wait({cancelling}, timeout=0.5)
    assert not done, "cancel must block on the consumer's claim lock, not read around it"

    await second_session.commit()
    cancelled = await asyncio.wait_for(cancelling, timeout=15)

    # Nothing was cancelled: post-lock, the task is terminal.
    assert cancelled == []
    await db_session.commit()
    status = (
        await db_session.execute(
            select(FulfillmentTask.status).where(FulfillmentTask.id == claimed_id)
        )
    ).scalar_one()
    assert status == "succeeded"


async def test_sibling_drainers_settle_the_order_exactly_once_and_never_lose_it(
    db_session: AsyncSession, second_session: AsyncSession
) -> None:
    """Two drainers split one order's tasks; the order must still settle.

    This is the lost-settle race, which is why ``_try_settle_order`` locks the
    order *before* reading the tasks. Each drainer finishes one sibling and
    then looks at the order: neither can see the other's uncommitted work
    (MVCC), so on a read-then-lock implementation both decide "not all
    succeeded yet" and bail — and the order sits in ``fulfilling`` forever
    with every task succeeded, a state no admin path can repair (retry and
    cancel both refuse a ``succeeded`` task).

    ``limit=1`` is what splits the batch deterministically: the first drainer
    claims exactly one task and holds it, ``SKIP LOCKED`` hands the second
    drainer the other one.
    """
    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session, tag="settle-race", n_items=2)
    order_id = order.id
    await ff_svc.start_for_order(db_session, order_id=order_id, settings=cfg)
    await db_session.commit()

    # Drainer A: claims one sibling, runs it, tries to settle -- and must not,
    # because B's task is still pending from where A is standing. A now holds
    # the order-row lock (and its task row) until it commits.
    assert await ff_svc.drain_pending_tasks(db_session, limit=1) == 1
    assert (
        await db_session.execute(select(Order.status).where(Order.id == order_id))
    ).scalar_one() == "fulfilling"

    # Drainer B: claims the other sibling, runs it, and blocks trying to
    # settle -- read-then-lock would let it read around A and bail instead.
    draining_b = asyncio.create_task(ff_svc.drain_pending_tasks(second_session, limit=1))
    done, _pending = await asyncio.wait({draining_b}, timeout=0.5)
    assert not done, "the second drainer must block on the order lock, not read around it"

    await db_session.commit()
    assert await asyncio.wait_for(draining_b, timeout=15) == 1
    await second_session.commit()

    status = (
        await db_session.execute(select(Order.status).where(Order.id == order_id))
    ).scalar_one()
    assert status == "delivered"  # settled by the drainer that finished last

    delivered_events = (
        await db_session.execute(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.order_id == order_id, OrderEvent.kind == "order.delivered")
        )
    ).scalar_one()
    assert delivered_events == 1  # and settled exactly once


async def test_a_retry_cannot_declare_money_whole_that_an_earlier_attempt_may_have_spent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full path of the rule ``record_money_outcome`` enforces.

    Not a unit test of that function: the point is that the answer survives
    ``retry_task`` on a real row, because that is the step that used to erase
    it. The sequence needs no supplier misbehaviour — a charge that lands and
    then 500s, the ordinary admin Retry, and a transient outage on the replay:

    1. ``fulfill`` raises with ``UNKNOWN`` — the charge may have gone through.
    2. Retry. The task goes back to ``pending``; the answer must not.
    3. The replay raises with ``RETURNED`` — true of *that* attempt, which
       never reached the supplier at all.

    If step 3 won, M3b Task 3 would refund a deposit for goods we had already
    paid for.
    """
    # A phase switch rather than a queue: the saga may call ``fulfill`` more
    # than once per phase (an inventory route falling back to a supplier is one
    # way), and the test is about which answer *wins*, not about call counts.
    answer = {"value": MoneyOutcome.UNKNOWN}
    calls = {"n": 0}

    async def _fail_with_the_phases_answer(
        self: MockFulfiller,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        calls["n"] += 1
        raise FulfillerError("supplier said no", money_outcome=answer["value"])

    monkeypatch.setattr(MockFulfiller, "fulfill", _fail_with_the_phases_answer)

    order = await _make_paid_order(db_session, tag="promote")
    await ff_svc.start_for_order(db_session, order_id=order.id, settings=_settings())
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order.id)
        )
    ).scalar_one()

    assert task.status == "failed"
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.UNKNOWN

    await ff_svc.retry_task(db_session, task_id=task.id)
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.UNKNOWN, "retry must not erase it"

    answer["value"] = MoneyOutcome.RETURNED
    before = calls["n"]
    await ff_svc.process_task(db_session, task_id=task.id)

    assert calls["n"] > before, "the replay actually ran"
    assert task.status == "failed"
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.UNKNOWN
