"""The fulfilment inbox's supplier switch: who can take a task, and at what price.

Split from ``service.py`` (already far past the 400-line soft limit). Read-only:
it quotes suppliers through ``cost_refresh.quote_mapping`` and writes nothing —
the move itself is ``service.reassign_task``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import NotFoundError
from yupay.modules.fulfillment.service import _NOT_REASSIGNABLE, _load_task
from yupay.modules.orders.models import OrderItem


async def reassign_options(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    """The suppliers this task can be moved onto, each with its live price.

    Exactly the targets :func:`reassign_task` would accept: an active,
    non-delisted mapping for the line's SKU, a supplier the registry knows,
    not the warehouse or the manual queue, not the one the task is on. Each is
    quoted live (``cost_refresh.quote_mapping``, read-only) and sorted
    cheapest first, so the operator picks on price without opening Sourcing.
    """
    from yupay.modules.catalog.models import Sku
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.integrations.cost_refresh import quote_mapping
    from yupay.modules.integrations.models import (
        CATALOG_DELISTED,
        RESERVE_SUPPLIERS,
        SkuSupplierMapping,
    )
    from yupay.modules.sourcing.brand_overview import _stock_by_sku_supplier

    task = await _load_task(db, task_id, for_update=False)
    item = await db.get(OrderItem, task.order_item_id)
    sku = await db.get(Sku, item.sku_id) if item is not None else None
    if item is None or sku is None:
        raise NotFoundError("order line not found", extra={"task_id": task_id})
    mappings = [
        m
        for m in (
            await db.execute(
                select(SkuSupplierMapping).where(
                    SkuSupplierMapping.sku_id == sku.id,
                    SkuSupplierMapping.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
        if m.supplier_slug in REGISTRY
        and m.supplier_slug not in _NOT_REASSIGNABLE
        and m.supplier_slug != task.supplier
        and not (m.extra or {}).get(CATALOG_DELISTED)
    ]
    stock = await _stock_by_sku_supplier(db, mappings)
    options: list[dict[str, Any]] = []
    for mapping in mappings:
        cost, reason = await quote_mapping(db, mapping)
        options.append(
            {
                "supplier": mapping.supplier_slug,
                "cost_usdt": cost,
                "cost_reason": reason,
                "stock": stock.get((sku.id, mapping.supplier_slug), (None, None))[0],
                "reserve": mapping.supplier_slug in RESERVE_SUPPLIERS,
            }
        )
    options.sort(key=lambda o: (o["cost_usdt"] is None, o["cost_usdt"] or 0, o["supplier"]))
    return {
        "sku_id": sku.id,
        "sku_code": sku.sku_code,
        "price_usd": item.unit_price_usd,
        "options": options,
    }
