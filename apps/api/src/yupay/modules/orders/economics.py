"""What an order cost us and what we kept — the admin order page's «Закупка и маржа».

Per line: what the customer was charged, what the goods cost, the margin, and which
supplier delivered it. The figures come from the same expressions the business tab sums
(:mod:`.revenue`), so an order's margin here is exactly its share of the dashboard's —
the gross from :func:`~.revenue.charged_usd_expr`, the margin from
:func:`~.revenue.margin_usd_expr`, and the cost as their difference, so
``charged - margin == cost`` holds by construction.

The cost is **frozen** when the line carries the cost it was bought at (snapshotted at
checkout, re-frozen on a supplier switch, or written from what the supplier actually
took); otherwise it is an **estimate** from the price history or today's price, and the
page says so. Today's supplier price is shown beside it so «купили за / покупаем за»
reads at a glance. A line whose cost nobody knows has no margin, not a 100 % one.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.catalog.models import Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import charged_usd_expr, margin_usd_expr

_CENTS = Decimal("0.01")
_UNIT = Decimal("0.0001")

CostSource = Literal["frozen", "estimated"]


class LineEconomicsOut(BaseModel):
    """One order line's money."""

    item_id: str
    label: str
    qty: int
    #: Which supplier the line's latest fulfilment task went to; ``None`` before one exists.
    supplier: str | None
    charged_usd: Decimal
    #: ``None`` when the cost is unknown — and then so is the margin.
    cost_usd: Decimal | None
    unit_cost_usd: Decimal | None
    cost_source: CostSource | None
    #: Today's price of one unit at the SKU's routed supplier, for comparison.
    current_unit_cost_usd: Decimal | None
    margin_usd: Decimal | None
    margin_pct: Decimal | None
    #: The line's share of an affiliate discount, already taken off ``charged_usd``.
    discount_usd: Decimal


class OrderEconomicsOut(BaseModel):
    """``GET /admin/orders/{id}/economics``."""

    lines: list[LineEconomicsOut]
    charged_usd: Decimal
    #: Sums over the lines whose cost is known; ``unknown_lines`` says how many are not.
    cost_usd: Decimal | None
    margin_usd: Decimal | None
    margin_pct: Decimal | None
    unknown_lines: int


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    if whole == 0:
        return None
    return (part / whole * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


async def order_economics(db: AsyncSession, *, order_id: str) -> OrderEconomicsOut:
    """The order's purchase cost and margin, line by line.

    Args:
        db: Session.
        order_id: The order; the caller has already checked it exists.

    Returns:
        Lines in item order and the totals over them.
    """
    # Lazy: fulfillment imports orders, so the model cannot be a top-level import here.
    from yupay.modules.fulfillment.models import FulfillmentTask

    rows = (
        await db.execute(
            select(
                OrderItem.id,
                OrderItem.qty,
                OrderItem.cost_usdt,
                OrderItem.discount_usd,
                Sku.sku_code,
                Sku.denomination,
                Sku.variable_amount,
                Sku.cost_usdt.label("live_cost"),
                charged_usd_expr().label("charged"),
                margin_usd_expr().label("margin"),
            )
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.created_at, OrderItem.id)
        )
    ).all()
    tasks = (
        await db.execute(
            select(FulfillmentTask.order_item_id, FulfillmentTask.supplier)
            .where(FulfillmentTask.order_id == order_id)
            .order_by(FulfillmentTask.created_at)
        )
    ).all()
    supplier_of = {t.order_item_id: t.supplier for t in tasks}  # the latest wins

    lines: list[LineEconomicsOut] = []
    for r in rows:
        charged = Decimal(r.charged).quantize(_CENTS, rounding=ROUND_HALF_UP)
        margin = (
            None if r.margin is None else Decimal(r.margin).quantize(_CENTS, rounding=ROUND_HALF_UP)
        )
        cost = None if margin is None else charged - margin
        lines.append(
            LineEconomicsOut(
                item_id=r.id,
                label=r.denomination or r.sku_code,
                qty=r.qty,
                supplier=supplier_of.get(r.id),
                charged_usd=charged,
                cost_usd=cost,
                unit_cost_usd=(
                    None
                    if cost is None or r.qty == 0
                    # The discount leaves the cost alone: it is off both gross and margin.
                    else (cost / r.qty).quantize(_UNIT)
                ),
                cost_source=(
                    None if cost is None else "frozen" if r.cost_usdt is not None else "estimated"
                ),
                current_unit_cost_usd=(
                    None if r.live_cost is None or r.variable_amount else Decimal(r.live_cost)
                ),
                margin_usd=margin,
                margin_pct=None if margin is None else _pct(margin, charged),
                discount_usd=Decimal(r.discount_usd or 0),
            )
        )

    known = [line for line in lines if line.margin_usd is not None]
    charged_total = sum((line.charged_usd for line in lines), Decimal("0"))
    known_charged = sum((line.charged_usd for line in known), Decimal("0"))
    margin_total = sum((line.margin_usd or Decimal("0") for line in known), Decimal("0"))
    return OrderEconomicsOut(
        lines=lines,
        charged_usd=charged_total,
        cost_usd=None if not known else known_charged - margin_total,
        margin_usd=None if not known else margin_total,
        margin_pct=None if not known else _pct(margin_total, known_charged),
        unknown_lines=len(lines) - len(known),
    )


__all__ = ["LineEconomicsOut", "OrderEconomicsOut", "order_economics"]
