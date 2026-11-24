"""The hourly smart-routing pass on real rows (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.orders.models import OrderItem
from yupay.modules.sourcing import smart_routing
from yupay.modules.sourcing.models import (
    SkuSourcingRule,
    SourcingQuarantine,
    SourcingSettings,
    SourcingSwitchLog,
)

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio

#: What the stubbed live re-quote answers at switch time, per SKU (default 0.95).
LIVE: dict[str, Decimal | None] = {}


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """The job opens its own sessions; point them at the test database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(smart_routing, "get_session_factory", lambda: factory)


@pytest.fixture(autouse=True)
def _live_reprice(monkeypatch: pytest.MonkeyPatch) -> None:
    LIVE.clear()

    async def _quote(db: AsyncSession, *, sku_id: str, **kwargs: Any) -> SimpleNamespace:
        cost = LIVE.get(sku_id, Decimal("0.95"))
        return SimpleNamespace(
            wrote_cost=cost is not None, new_cost=cost, reason=None if cost else "no price"
        )

    monkeypatch.setattr("yupay.modules.integrations.cost_refresh.refresh_routed_cost", _quote)


async def _mode(db: AsyncSession, mode: str) -> None:
    row = await db.get(SourcingSettings, 1)
    if row is None:
        row = SourcingSettings(id=1)
        db.add(row)
    row.smart_mode = mode
    await db.commit()


async def _sku(
    db: AsyncSession, tag: str, *, managed: bool, nova_cost: str, fresh: bool = True
) -> str:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    sku = await db.get(Sku, item.sku_id)
    assert sku is not None
    sku.cost_usdt = Decimal("1.00")
    for slug, cost in (("g2b", "1.00"), ("nova", nova_cost)):
        db.add(
            SkuSupplierMapping(
                sku_id=sku.id,
                supplier_slug=slug,
                kind="game",
                external_product_id=f"{tag}-{slug}",
                is_active=True,
            )
        )
        await db.flush()
        await db.execute(
            text(
                "INSERT INTO supplier_price_state (sku_id, supplier_slug, cost_usdt, checked_at)"
                " VALUES (CAST(:sku AS uuid), :slug, :cost,"
                " now() - make_interval(hours => :age))"
            ),
            {
                "sku": sku.id,
                "slug": slug,
                "cost": Decimal(cost),
                "age": 0 if fresh or slug == "g2b" else 5,
            },
        )
    db.add(
        SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="g2b", managed=managed)
    )
    await db.commit()
    return sku.id


async def _rule(db: AsyncSession, sku_id: str) -> SkuSourcingRule:
    rule = await db.get(SkuSourcingRule, sku_id, populate_existing=True)
    assert rule is not None
    return rule


async def _log(db: AsyncSession, sku_id: str) -> list[tuple[str, str | None, bool]]:
    rows = (
        (await db.execute(select(SourcingSwitchLog).where(SourcingSwitchLog.sku_id == sku_id)))
        .scalars()
        .all()
    )
    return [(r.reason, r.to_supplier, r.applied) for r in rows]


async def test_on_moves_a_managed_rule_to_the_cheaper_supplier(db_session: AsyncSession) -> None:
    await _mode(db_session, "on")
    sku_id = await _sku(db_session, "sr-on", managed=True, nova_cost="0.95")
    await smart_routing.run_smart_routing()
    assert (await _rule(db_session, sku_id)).supplier_slug == "nova"
    assert await _log(db_session, sku_id) == [("cheaper", "nova", True)]


async def test_shadow_only_logs_and_logs_once(db_session: AsyncSession) -> None:
    await _mode(db_session, "shadow")
    sku_id = await _sku(db_session, "sr-shadow", managed=True, nova_cost="0.95")
    await smart_routing.run_smart_routing()
    await smart_routing.run_smart_routing()
    assert (await _rule(db_session, sku_id)).supplier_slug == "g2b"
    assert await _log(db_session, sku_id) == [("cheaper", "nova", False)]


async def test_a_pinned_rule_is_never_moved(db_session: AsyncSession) -> None:
    await _mode(db_session, "on")
    sku_id = await _sku(db_session, "sr-pin", managed=False, nova_cost="0.95")
    await smart_routing.run_smart_routing()
    assert (await _rule(db_session, sku_id)).supplier_slug == "g2b"


async def test_a_stale_price_moves_nothing(db_session: AsyncSession) -> None:
    await _mode(db_session, "on")
    sku_id = await _sku(db_session, "sr-stale", managed=True, nova_cost="0.95", fresh=False)
    await smart_routing.run_smart_routing()
    assert (await _rule(db_session, sku_id)).supplier_slug == "g2b"
    assert await _log(db_session, sku_id) == []


async def test_a_switch_the_live_price_does_not_back_is_undone(db_session: AsyncSession) -> None:
    await _mode(db_session, "on")
    sku_id = await _sku(db_session, "sr-verify", managed=True, nova_cost="0.95")
    LIVE[sku_id] = Decimal("1.10")  # nova's real price now is dearer than stored
    await smart_routing.run_smart_routing()
    assert (await _rule(db_session, sku_id)).supplier_slug == "g2b"
    assert await _log(db_session, sku_id) == [("verify_failed", "nova", False)]


async def test_three_failures_in_a_day_quarantine_the_supplier(db_session: AsyncSession) -> None:
    await _mode(db_session, "on")
    sku_id = await _sku(db_session, "sr-q", managed=True, nova_cost="1.00")
    LIVE[sku_id] = Decimal("1.00")
    for n in range(3):
        order = await _make_paid_order(db_session, tag=f"sr-q-{n}")
        item = (
            await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
        ).scalar_one()
        item.sku_id = sku_id
        db_session.add(
            FulfillmentTask(
                id=new_id(),
                order_id=order.id,
                order_item_id=item.id,
                supplier="g2b",
                status="failed",
            )
        )
    await db_session.commit()
    await smart_routing.run_smart_routing()
    q = await db_session.get(SourcingQuarantine, (sku_id, "g2b"))
    assert q is not None
    assert q.strikes == 1
    # Quarantined, the route moves to the other supplier at the same price.
    assert (await _rule(db_session, sku_id)).supplier_slug == "nova"
