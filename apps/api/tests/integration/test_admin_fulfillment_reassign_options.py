"""``GET /admin/fulfillment/tasks/{id}/reassign-options`` — who can take a task.

Pins the filter the operator relies on: only suppliers with an active,
non-delisted mapping for the line's SKU, never the supplier the task is
already on, cheapest first, and a supplier that cannot be quoted listed with a
reason rather than dropped. The live quote is stubbed — this file pins the
selection and the ordering, not each supplier's price parsing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.integrations import cost_refresh
from yupay.modules.integrations.models import CATALOG_DELISTED, SkuSupplierMapping
from yupay.modules.orders.models import OrderItem

from tests.integration.test_admin_fulfillment_bulk_routes import _admin_headers, _make_task

pytestmark = pytest.mark.asyncio

__all__ = ["_admin_headers"]

PRICES = {"g2b": Decimal("1.20"), "gengine": Decimal("0.95")}


async def _map(db: AsyncSession, sku_id: str, supplier: str, **extra: Any) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug=supplier,
            kind="game",
            external_product_id=f"{supplier}-game",
            external_variant_id=f"{supplier}-v",
            quantity=1,
            extra=extra,
            is_active=True,
            updated_by="test",
        )
    )


async def test_only_mapped_suppliers_cheapest_first(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_quote(
        _db: AsyncSession, mapping: SkuSupplierMapping
    ) -> tuple[Decimal | None, str | None]:
        price = PRICES.get(mapping.supplier_slug)
        return (price, None) if price is not None else (None, "нет в каталоге")

    monkeypatch.setattr(cost_refresh, "quote_mapping", fake_quote)

    task_id = await _make_task(db_session, status="failed", supplier="fzr")
    task = await db_session.get(FulfillmentTask, task_id)
    assert task is not None
    sku_id = (
        await db_session.execute(select(OrderItem.sku_id).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    for supplier in ("g2b", "gengine", "nova", "fzr"):
        await _map(db_session, sku_id, supplier)
    await db_session.commit()
    # A delisted mapping is not a target: the supplier no longer sells it.
    delisted = await db_session.get(SkuSupplierMapping, (sku_id, "nova"))
    assert delisted is not None
    delisted.extra = {CATALOG_DELISTED: True}
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reassign-options", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [o["supplier"] for o in body["options"]] == ["gengine", "g2b"]
    assert body["options"][0]["cost_usdt"] == "0.95"
    assert Decimal(body["price_usd"]) == Decimal("1")


async def test_unquotable_supplier_stays_listed_with_a_reason(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_price(
        _db: AsyncSession, _mapping: SkuSupplierMapping
    ) -> tuple[Decimal | None, str | None]:
        return None, "нет в каталоге"

    monkeypatch.setattr(cost_refresh, "quote_mapping", no_price)
    task_id = await _make_task(db_session, status="failed", supplier="manual")
    task = await db_session.get(FulfillmentTask, task_id)
    assert task is not None
    sku_id = (
        await db_session.execute(select(OrderItem.sku_id).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    await _map(db_session, sku_id, "g2b")
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reassign-options", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    [only] = r.json()["options"]
    assert only == {
        "supplier": "g2b",
        "cost_usdt": None,
        "cost_reason": "нет в каталоге",
        "stock": None,
        "reserve": False,
    }


async def test_requires_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.get(f"/api/v1/admin/fulfillment/tasks/{new_id()}/reassign-options")
    assert r.status_code == 401
