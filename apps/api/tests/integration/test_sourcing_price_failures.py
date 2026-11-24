"""Dead-mapping report and the comparison's price reason (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.orders.models import OrderItem
from yupay.modules.sourcing.brand_overview import _price_failure, _supplier_cost
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.sourcing.price_failures import price_failures

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio


async def _state(db: AsyncSession, sku_id: str, slug: str, *, ok_hours: int | None) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id, supplier_slug=slug, kind="game", external_product_id="x", is_active=True
        )
    )
    await db.flush()
    await db.execute(
        text(
            "INSERT INTO supplier_price_state (sku_id, supplier_slug, cost_usdt, checked_at,"
            " failed_at, last_error) VALUES (CAST(:sku AS uuid), :slug, :cost,"
            " CASE WHEN CAST(:h AS int) IS NULL THEN NULL"
            " ELSE now() - make_interval(hours => CAST(:h AS int)) END,"
            " now(), 'offer «weekly» не найден в каталоге FazerCards')"
        ),
        {"sku": sku_id, "slug": slug, "cost": Decimal("1") if ok_hours else None, "h": ok_hours},
    )


async def test_routed_dead_mappings_come_first_and_fresh_failures_wait(
    db_session: AsyncSession,
) -> None:
    order = await _make_paid_order(db_session, tag="pf")
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalar_one()
    await _state(db_session, item.sku_id, "fzr", ok_hours=None)  # never priced, routed
    await _state(db_session, item.sku_id, "g2b", ok_hours=48)  # good two days ago
    await _state(db_session, item.sku_id, "nova", ok_hours=2)  # good two hours ago: not dead
    db_session.add(SkuSourcingRule(sku_id=item.sku_id, mode="force_supplier", supplier_slug="fzr"))
    await db_session.commit()

    report = await price_failures(db_session, hours=24, supplier=None, limit=50)
    mine = [i for i in report.items if i.sku_id == item.sku_id]
    assert [(i.supplier_slug, i.routed) for i in mine] == [("fzr", True), ("g2b", False)]
    assert any(g.error == "offer «…» не найден в каталоге FazerCards" for g in report.groups)


def test_the_comparison_prefers_the_checked_price_and_shows_a_newer_failure() -> None:
    from datetime import UTC, datetime, timedelta

    t = datetime(2026, 11, 24, tzinfo=UTC)
    assert _supplier_cost((Decimal("2"), t, None, None), None, routed_cost=None) == (
        "checked",
        "2",
        t,
    )
    assert _price_failure((Decimal("2"), t, t + timedelta(hours=1), "gone")) == {
        "price_failed_at": t + timedelta(hours=1),
        "price_error": "gone",
    }
    assert _price_failure((Decimal("2"), t + timedelta(hours=1), t, "old")) == {}
