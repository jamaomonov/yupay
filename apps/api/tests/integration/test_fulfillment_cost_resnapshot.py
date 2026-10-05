"""A route switch re-freezes the line's cost from the supplier it goes to.

Pins the analytics half of a supplier switch: the line was costed at checkout
from the routed supplier; after an admin reassign or the inventory fallback
it is bought from another one, and ``OrderItem.cost_usdt`` has to say so or
every margin report subtracts the wrong supplier's price. Three shapes: a
live quote, the price-history fallback when the quote fails, and "kept" with
a reason when neither exists — the switch itself never fails over this.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as fulfillment_service
from yupay.modules.fulfillment.models import FulfillmentAttempt, FulfillmentTask
from yupay.modules.integrations import cost_refresh
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierPriceHistory
from yupay.modules.orders.models import OrderItem

from tests.integration.test_admin_fulfillment_bulk_routes import _admin_headers, _make_task
from tests.integration.test_admin_fulfillment_reassign_options import _map

pytestmark = pytest.mark.asyncio

__all__ = ["_admin_headers"]


async def _line_of(db: AsyncSession, task_id: str) -> OrderItem:
    task = await db.get(FulfillmentTask, task_id)
    assert task is not None
    item = await db.get(OrderItem, task.order_item_id)
    assert item is not None
    return item


async def _switch_payload(db: AsyncSession, task_id: str) -> dict[str, object]:
    rows = (
        await db.execute(
            select(FulfillmentAttempt.payload).where(FulfillmentAttempt.task_id == task_id)
        )
    ).scalars()
    switches = [p for p in rows if "route_switch" in p]
    assert switches, "no route_switch attempt recorded"
    return switches[0]


async def test_reassign_refreezes_cost_from_the_new_suppliers_quote(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def quote(
        _db: AsyncSession, mapping: SkuSupplierMapping
    ) -> tuple[Decimal | None, str | None]:
        assert mapping.supplier_slug == "g2b"
        return Decimal("0.80"), None

    monkeypatch.setattr(cost_refresh, "quote_mapping", quote)
    task_id = await _make_task(db_session, status="failed", supplier="fzr")
    item = await _line_of(db_session, task_id)
    item.cost_usdt = Decimal("0.90")  # what fzr, the routed supplier, cost at checkout
    await _map(db_session, item.sku_id, "g2b")
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reassign",
        headers=_admin_headers,
        json={"supplier": "g2b"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    item = await _line_of(db_session, task_id)
    assert item.cost_usdt == Decimal("0.80")
    payload = await _switch_payload(db_session, task_id)
    assert payload["cost_was"] == "0.900000"
    assert payload["cost_usdt"] == "0.800000"
    assert payload["cost_source"] == "quote"


async def test_a_failed_quote_falls_back_to_that_suppliers_price_history(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_quote(
        _db: AsyncSession, _mapping: SkuSupplierMapping
    ) -> tuple[Decimal | None, str | None]:
        return None, "timeout"

    monkeypatch.setattr(cost_refresh, "quote_mapping", no_quote)
    task_id = await _make_task(db_session, status="failed", supplier="fzr")
    item = await _line_of(db_session, task_id)
    item.cost_usdt = Decimal("0.90")
    await _map(db_session, item.sku_id, "g2b")
    db_session.add(
        SupplierPriceHistory(
            id=new_id(),
            sku_id=item.sku_id,
            supplier_slug="g2b",
            kind="game",
            external_product_id="g2b-game",
            cost_usdt=Decimal("0.85"),
        )
    )
    # A newer row for the *other* supplier must not be picked.
    db_session.add(
        SupplierPriceHistory(
            id=new_id(),
            sku_id=item.sku_id,
            supplier_slug="fzr",
            kind="game",
            external_product_id="fzr-game",
            cost_usdt=Decimal("0.70"),
        )
    )
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reassign",
        headers=_admin_headers,
        json={"supplier": "g2b"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    item = await _line_of(db_session, task_id)
    assert item.cost_usdt == Decimal("0.85")
    payload = await _switch_payload(db_session, task_id)
    assert payload["cost_source"] == "history"


async def test_inventory_fallback_keeps_the_cost_and_says_why(
    db_session: AsyncSession,
) -> None:
    """The warehouse is empty and sourcing falls back to a supplier that has
    no price feed and no history. The line keeps its cost, the switch still
    happens, and the attempt names the reason."""
    task_id = await _make_task(db_session, status="pending", supplier="inventory")
    item = await _line_of(db_session, task_id)
    item.cost_usdt = Decimal("0.90")
    await _map(db_session, item.sku_id, "mock")
    await db_session.commit()

    task = await fulfillment_service.process_task(db_session, task_id=task_id)
    await db_session.commit()
    assert task.supplier != "inventory"

    db_session.expire_all()
    item = await _line_of(db_session, task_id)
    assert item.cost_usdt == Decimal("0.90")
    payload = await _switch_payload(db_session, task_id)
    assert payload["reason"] == "inventory_no_stock"
    assert payload["route_switch"] == task.supplier
    assert payload["cost_was"] == "0.900000"
    assert payload["cost_kept"]  # no mapping or no price feed: a reason, not a number
    assert "cost_usdt" not in payload
