"""``fulfillment.service._record_supplier_charge`` — freezing what a supplier
actually took onto a variable-amount line.

NOVA's fulfiller already proves (``test_nova_fulfiller.py``) that its
``FulfillResult``/``FulfillStatus`` carry ``supplier_charged_usd`` when NOVA
states one. What this file owns is the saga's side of the contract: both
metadata-merge sites in ``fulfillment/service.py`` — the fulfil path
(``process_task``, which calls a supplier's ``fulfill()``) and the poll path
(``process_webhook_update``, which calls ``check_status()``) — must call the
recording helper with whatever the adapter merged in, and the helper must
only ever act on a variable-amount SKU, only from a figure actually present,
and only once.

A fake ``Fulfiller`` stands in for NOVA so each scenario controls exactly
what ``extra_metadata`` the saga sees, instead of re-deriving NOVA's own HTTP
contract (already covered elsewhere).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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
from yupay.modules.fulfillment.suppliers.base import FulfillResult, FulfillStatus
from yupay.modules.orders.models import Order, OrderItem

# Settlement on the poll path reaches for ``realtime.api`` -> ``admin.deps`` ->
# ``auth.deps`` lazily; importing the app first (as ``test_nova_reconcile.py``
# does for the same reason) loads that whole chain up front instead of mid
# partial-import, which is what breaks when this file runs alone.
import yupay.main  # noqa: F401  isort:skip

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeFulfiller:
    """A supplier whose ``fulfill``/``check_status`` answers are fixed by the
    test, so each scenario controls exactly the ``extra_metadata`` the saga
    sees without reproducing NOVA's own HTTP contract."""

    supplier: str = "nova"
    fulfill_result: FulfillResult | None = None
    status_result: FulfillStatus | None = None
    calls: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return True

    async def fulfill(
        self, *, db: AsyncSession, order: Order, item: OrderItem, idempotency_key: str
    ) -> FulfillResult:
        self.calls.append("fulfill")
        assert self.fulfill_result is not None
        return self.fulfill_result

    async def check_status(self, *, db: AsyncSession, task: FulfillmentTask) -> FulfillStatus:
        self.calls.append("check_status")
        assert self.status_result is not None
        return self.status_result

    async def cancel(self, *, db: AsyncSession, task: FulfillmentTask) -> None:
        raise AssertionError("not exercised in this file")


async def _seed_sku(db: AsyncSession, slug: str, *, variable: bool) -> str:
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
    db.add_all([category, brand, product])
    await db.flush()
    # ``ck_skus_variable_amount_complete`` requires bounds + a multiplier
    # whenever ``variable_amount`` is true.
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{slug}",
        price_usd=Decimal("10.00"),
        variable_amount=variable,
        min_amount_usd=Decimal("1.00") if variable else None,
        max_amount_usd=Decimal("1000.00") if variable else None,
        rate_multiplier=Decimal("1.10") if variable else None,
        sort_order=10,
        active=True,
    )
    db.add(sku)
    await db.flush()
    return sku.id


async def _seed_task(
    db: AsyncSession, *, sku_id: str, tag: str, cost: str | None = None
) -> FulfillmentTask:
    """An Order + OrderItem + a pending ``nova`` task, bypassing
    checkout/sourcing entirely — same shape as ``test_nova_reconcile.py``'s
    ``_seed_task``. ``cost`` pre-populates ``item.cost_usdt``, for the
    write-once scenario."""
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=f"{tag}@example.test",
        status="fulfilling",
        currency="USD",
        total_usd=Decimal("10.00"),
        total_charged=Decimal("10.00"),
        expires_at=now() + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=Decimal("10.00"),
        cost_usdt=Decimal(cost) if cost is not None else None,
        fulfillment_state="pending",
    )
    db.add(item)
    await db.flush()
    task = FulfillmentTask(
        id=new_id(),
        order_id=order.id,
        order_item_id=item.id,
        supplier="nova",
        status="pending",
    )
    db.add(task)
    await db.commit()
    return task


def _result(*, extra: dict[str, Any]) -> FulfillResult:
    return FulfillResult(
        outcome="succeeded",
        external_order_id="nv-1",
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata=extra,
        money_outcome=None,
    )


def _status(*, extra: dict[str, Any]) -> FulfillStatus:
    return FulfillStatus(
        outcome="succeeded",
        artifact_kind=None,
        artifact=None,
        error=None,
        money_outcome=None,
        extra_metadata=extra,
    )


async def _reload_item(db: AsyncSession, item_id: str) -> OrderItem:
    return (
        await db.execute(
            select(OrderItem)
            .where(OrderItem.id == item_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_the_fulfil_path_records_a_stated_charge_on_a_variable_sku(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sku_id = await _seed_sku(db_session, "fulfil-var", variable=True)
    task = await _seed_task(db_session, sku_id=sku_id, tag="fulfil-var")
    fake = _FakeFulfiller(fulfill_result=_result(extra={"supplier_charged_usd": "9.80"}))
    monkeypatch.setattr(ff_svc, "get_fulfiller", lambda slug: fake)

    await ff_svc.process_task(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt == Decimal("9.80")


async def test_the_fulfil_path_writes_nothing_without_a_stated_charge(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sku_id = await _seed_sku(db_session, "fulfil-nocharge", variable=True)
    task = await _seed_task(db_session, sku_id=sku_id, tag="fulfil-nocharge")
    # Metadata present, but with no charge in it — e.g. only ``nova_status``.
    fake = _FakeFulfiller(fulfill_result=_result(extra={"nova_status": "completed"}))
    monkeypatch.setattr(ff_svc, "get_fulfiller", lambda slug: fake)

    await ff_svc.process_task(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt is None


async def test_a_fixed_price_sku_is_left_alone_even_with_a_stated_charge(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fixed SKU already froze its cost at checkout from the catalogue
    (ADR-0053) — a supplier's own figure must never overwrite that."""
    sku_id = await _seed_sku(db_session, "fulfil-fixed", variable=False)
    task = await _seed_task(db_session, sku_id=sku_id, tag="fulfil-fixed")
    fake = _FakeFulfiller(fulfill_result=_result(extra={"supplier_charged_usd": "9.80"}))
    monkeypatch.setattr(ff_svc, "get_fulfiller", lambda slug: fake)

    await ff_svc.process_task(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt is None


async def test_a_later_poll_never_moves_a_cost_the_create_already_wrote(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The create's figure is what margin has already been reported against.
    A poll's restatement — even a different number — must not move it."""
    sku_id = await _seed_sku(db_session, "poll-no-overwrite", variable=True)
    task = await _seed_task(db_session, sku_id=sku_id, tag="poll-no-overwrite")
    fake = _FakeFulfiller(fulfill_result=_result(extra={"supplier_charged_usd": "9.80"}))
    monkeypatch.setattr(ff_svc, "get_fulfiller", lambda slug: fake)
    await ff_svc.process_task(db_session, task_id=task.id)
    await db_session.commit()
    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt == Decimal("9.80")

    # Re-arm the task as if it were still being polled, then have the poll
    # report a *different* charge.
    task.status = "in_progress"
    await db_session.commit()
    fake.status_result = _status(extra={"supplier_charged_usd": "9.99"})

    await ff_svc.process_webhook_update(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt == Decimal("9.80"), "the create's figure must survive the poll"


async def test_the_poll_records_a_charge_the_create_never_stated(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For some orders the poll is the ONLY recording path.

    A NOVA create that answers without its debit block carries no charge at
    all — pinned on the client side by "an order without a debit gains no
    charge key". Those orders learn what they cost on a later poll, and if the
    poll path were unwired, or wired and then deleted, they would never record
    one. The test above this cannot see that: it asserts the value the create
    already wrote, which a poll that does nothing whatsoever also satisfies.
    """
    sku_id = await _seed_sku(db_session, "poll-only", variable=True)
    task = await _seed_task(db_session, sku_id=sku_id, tag="poll-only")
    # The create states nothing — the shape their API actually produces when
    # `novaDebit` is absent.
    fake = _FakeFulfiller(fulfill_result=_result(extra={"nova_status": "processing"}))
    monkeypatch.setattr(ff_svc, "get_fulfiller", lambda slug: fake)
    await ff_svc.process_task(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt is None, "nothing was stated, so nothing may be recorded"

    task.status = "in_progress"
    await db_session.commit()
    fake.status_result = _status(extra={"supplier_charged_usd": "9.80"})

    await ff_svc.process_webhook_update(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt == Decimal("9.80")


@pytest.mark.parametrize("stated", ["0", "0.00", "-1.00", "NaN", "not a number"])
async def test_a_charge_that_is_not_a_cost_is_ignored_not_written(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, stated: str
) -> None:
    """A zero, a negative and a NaN are not costs, and writing one is worse
    than dropping it.

    `cost_usdt` carries a positive check, so a `0` reaches the database as an
    IntegrityError *after* the supplier was paid and the goods delivered — the
    saga rolls the task back and reports a delivered top-up as a failure for a
    human to settle. `NaN` is quieter and worse: Postgres sorts it above every
    numeric so the check passes, and every margin sum over that window reads
    NaN afterwards.
    """
    sku_id = await _seed_sku(db_session, f"bad-{stated}", variable=True)
    task = await _seed_task(db_session, sku_id=sku_id, tag=f"bad-{stated}")
    fake = _FakeFulfiller(fulfill_result=_result(extra={"supplier_charged_usd": stated}))
    monkeypatch.setattr(ff_svc, "get_fulfiller", lambda slug: fake)

    task = await ff_svc.process_task(db_session, task_id=task.id)
    await db_session.commit()

    item = await _reload_item(db_session, task.order_item_id)
    assert item.cost_usdt is None
    # And the order is still delivered: refusing the figure must not cost the
    # customer their top-up.
    assert task.status == "succeeded"
