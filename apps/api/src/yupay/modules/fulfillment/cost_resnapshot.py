"""Re-freeze a line's cost when its task changes supplier.

``OrderItem.cost_usdt`` is frozen at checkout from ``Sku.cost_usdt``, which is
the *routed* supplier's price (ADR-0053). The route can still change after
that: the warehouse is empty and sourcing falls back to a supplier, or an
operator moves a failed task onto another one. Until this module existed the
line kept the first supplier's cost through both — we bought from G2B at
G2B's price and every margin report subtracted FazerCards'. Measured on prod
2026-10-05 the gap was theoretical (no route switch had happened yet), but
the reassign screen now shows a price per supplier precisely so that
operators will switch, and the first switch would have mis-stated the margin
on the line it was taken to save.

So a route switch re-quotes the line from the supplier it is going to: the
same read-only lookup the reassign screen showed the operator
(:func:`~yupay.modules.integrations.cost_refresh.quote_mapping`), falling
back to the newest ``supplier_price_history`` row for that supplier when the
live quote fails. Variable-amount (Steam) lines are left alone — their cost is
written after fulfilment by ``_record_supplier_charge`` from what the supplier
actually took, and a quote is not that.

Nothing here raises: a line whose new cost cannot be learned keeps the old
one, and the route-switch attempt says so, because the switch itself must
not fail over analytics.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Sku
from yupay.modules.orders.models import OrderItem

log = get_logger(__name__)


async def resnapshot_line_cost(
    db: AsyncSession, *, item: OrderItem, supplier: str
) -> dict[str, Any]:
    """Freeze ``supplier``'s current cost onto ``item`` and describe what happened.

    Args:
        db: Session the caller is already writing the route switch in.
        item: The order line the task serves. Mutated in place when a cost is
            found.
        supplier: Slug of the supplier the task is being moved onto.

    Returns:
        Keys to merge into the route-switch attempt payload: ``cost_was``
        (the frozen cost before, as text or ``None``), and either ``cost_usdt``
        plus ``cost_source`` (``"quote"`` or ``"history"``) when a cost was
        found, or ``cost_kept`` with the reason when it was not.
    """
    from yupay.modules.integrations import cost_refresh
    from yupay.modules.integrations.models import SkuSupplierMapping, SupplierPriceHistory

    was = _text(item.cost_usdt)
    variable = (
        await db.execute(select(Sku.variable_amount).where(Sku.id == item.sku_id))
    ).scalar_one_or_none()
    if variable:
        return {"cost_was": was, "cost_kept": "variable-amount line is costed on delivery"}

    mapping = (
        await db.execute(
            select(SkuSupplierMapping).where(
                SkuSupplierMapping.sku_id == item.sku_id,
                SkuSupplierMapping.supplier_slug == supplier,
                SkuSupplierMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if mapping is None:
        return {"cost_was": was, "cost_kept": f"no active {supplier} mapping"}

    cost, reason = await cost_refresh.quote_mapping(db, mapping)
    source = "quote"
    if cost is None:
        cost = (
            await db.execute(
                select(SupplierPriceHistory.cost_usdt)
                .where(
                    SupplierPriceHistory.sku_id == item.sku_id,
                    SupplierPriceHistory.supplier_slug == supplier,
                )
                .order_by(SupplierPriceHistory.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        source = "history"
    if cost is None or cost <= 0:
        log.info(
            "fulfillment.cost_resnapshot.kept",
            order_item_id=item.id,
            supplier=supplier,
            reason=reason,
        )
        return {"cost_was": was, "cost_kept": reason or "no quote and no price history"}

    item.cost_usdt = Decimal(str(cost))
    return {"cost_was": was, "cost_usdt": _text(item.cost_usdt), "cost_source": source}


def _text(value: Decimal | None) -> str | None:
    """Six decimals, like the column — so a value read back from Postgres and
    one still in the session print the same in the attempt log."""
    return None if value is None else f"{Decimal(value):.6f}"


__all__ = ["resnapshot_line_cost"]
