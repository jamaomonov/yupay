"""Hand a task a supplier refused to the next cheapest one (ADR-0108, part 1b).

On prod (60 days to 2026-11-24) fzr refunded 367 retail tasks — about six a day,
each a manual refund — and for 338 of them another mapped supplier could have
delivered with a margin of 3 % or more. This moves such a task once, by itself,
through the same checks an operator's reassign makes (:func:`service.switch_supplier`),
and leaves the run to the worker.

**Only a definite refusal moves.** The task failed with ``MoneyOutcome.RETURNED``:
the supplier refunded, or refused before charging (``panel_grading``). A timeout,
a lost create, an unknown status — anything that might still deliver — never
moves: two suppliers could both deliver and both be paid.

**Never twice, never a one-time pack, never at a loss.** One hop per task
(``extra_metadata["auto_failover"]``). A one-time pack is refused by every
supplier for the same player, so it refunds to the balance instead
(``one_time_pack``). The new supplier must leave the configured margin of what the
buyer paid and be at most ``failover_max_step_pct`` dearer than the line's cost.

Off unless the admin switch says otherwise (``sourcing_settings.failover_mode``):
``retail`` moves only customer orders, ``all`` reseller orders too.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers import MoneyOutcome
from yupay.modules.orders.models import Order, OrderEvent, OrderItem

log = get_logger("yupay.fulfillment.auto_failover")

#: ``FulfillmentTask.extra_metadata`` key: the hop already made (or refused).
FAILOVER_KEY: Final = "auto_failover"
#: The order timeline event and the actor of the move.
EVENT_KIND: Final = "fulfillment.auto_failover"
ACTOR: Final = "system:auto_failover"
#: Suppliers whose refusals are not a supplier's to fix by another: a CS2 skin
#: is a specific listing, not a SKU two vendors both sell.
_NOT_FROM: Final = frozenset({"waxpeer", "csmarket", "manual", "inventory"})
_HUNDRED: Final = Decimal(100)


def _paid_per_unit(item: OrderItem) -> Decimal:
    """What the buyer paid for one unit of the line, net of its discount."""
    qty = max(item.qty or 1, 1)
    return item.unit_price_usd - (item.discount_usd or Decimal(0)) / qty


def pick_supplier(
    options: list[dict[str, Any]],
    *,
    paid: Decimal,
    previous_cost: Decimal | None,
    min_margin_pct: Decimal,
    max_step_pct: Decimal,
) -> tuple[dict[str, Any] | None, str]:
    """The cheapest option that keeps the margin and the step, and why none did.

    Args:
        options: ``reassign_options`` rows, cheapest first.
        paid: What the buyer paid per unit, USD.
        previous_cost: The line's cost at the refusing supplier, when known.
        min_margin_pct: Margin of ``paid`` that must remain.
        max_step_pct: How much dearer than ``previous_cost`` the new one may be.

    Returns:
        ``(option, "")`` or ``(None, reason)``.
    """
    ceiling = paid * (1 - min_margin_pct / _HUNDRED)
    if previous_cost is not None:
        ceiling = min(ceiling, previous_cost * (1 + max_step_pct / _HUNDRED))
    priced = [o for o in options if o["cost_usdt"] is not None and o.get("stock") != 0]
    if not priced:
        return None, "no_priced_alternative"
    for option in priced:
        if Decimal(option["cost_usdt"]) <= ceiling:
            return option, ""
    return None, "too_expensive"


async def _eligible(
    db: AsyncSession, task: FulfillmentTask, *, mode: str
) -> tuple[OrderItem, Order] | None:
    """The line and order when this failed task may move at all."""
    meta = task.extra_metadata or {}
    if (
        task.status != "failed"
        or task.supplier in _NOT_FROM
        or meta.get(FAILOVER_KEY)
        or meta.get("money_outcome") != MoneyOutcome.RETURNED.value
    ):
        return None
    item = await db.get(OrderItem, task.order_item_id)
    order = await db.get(Order, task.order_id)
    if item is None or order is None or order.status not in ("paid", "fulfilling"):
        return None
    if order.merchant_id is not None and mode != "all":
        return None
    sku = await db.get(Sku, item.sku_id)
    if sku is None or sku.one_time_pack:
        return None
    return item, order


async def try_failover(db: AsyncSession, *, task_id: str) -> bool:
    """Put a refused task on the next cheapest supplier; ``True`` when it moved.

    Never raises for an ordinary "no": every refusal is a ``False`` with the reason
    on the task. The caller contains unexpected faults.
    """
    from yupay.modules.fulfillment import service as ff_svc
    from yupay.modules.fulfillment.reassign_options import reassign_options
    from yupay.modules.sourcing import settings as sourcing_settings

    conf = await sourcing_settings.load(db)
    if conf.failover_mode == "off":
        return False
    task = await db.get(FulfillmentTask, task_id)
    if task is None:
        return False
    found = await _eligible(db, task, mode=conf.failover_mode)
    if found is None:
        return False
    item, order = found
    min_margin = (
        conf.failover_min_margin_b2b_pct
        if order.merchant_id is not None
        else conf.failover_min_margin_retail_pct
    )
    quotes = await reassign_options(db, task_id=task.id)
    option, reason = pick_supplier(
        quotes["options"],
        paid=_paid_per_unit(item),
        previous_cost=item.cost_usdt,
        min_margin_pct=min_margin,
        max_step_pct=conf.failover_max_step_pct,
    )
    previous = task.supplier
    stamp: dict[str, Any] = {"from": previous, "at": now().isoformat()}
    if option is None:
        # Remembered, so a later trigger on the same failure does not ask again.
        task.extra_metadata = {
            **(task.extra_metadata or {}),
            FAILOVER_KEY: {**stamp, "skipped": reason},
        }
        await db.flush()
        log.info("fulfillment.auto_failover.skipped", task_id=task.id, reason=reason)
        return False
    stamp |= {"to": option["supplier"], "cost_usdt": str(option["cost_usdt"])}
    task.extra_metadata = {**(task.extra_metadata or {}), FAILOVER_KEY: stamp}
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind=EVENT_KIND,
            payload={
                "task_id": task.id,
                "from": previous,
                "to": option["supplier"],
                "cost_usdt": str(option["cost_usdt"]),
                "error": (task.last_error or "")[:200],
            },
            actor=ACTOR,
        )
    )
    await db.flush()
    log.info(
        "fulfillment.auto_failover.moved",
        task_id=task.id,
        order_id=order.id,
        from_supplier=previous,
        to_supplier=option["supplier"],
    )
    # Switched, not run: the worker drains the task like any pending one. The
    # refusal may have been noticed inside a supplier webhook — a request
    # handler, where calling another supplier is not allowed (AGENTS.md §10).
    await ff_svc.switch_supplier(
        db, task_id=task.id, supplier=option["supplier"], admin_id=ACTOR, reason="auto_failover"
    )
    await db.execute(text("SELECT pg_notify('fulfillment_queue', :oid)"), {"oid": order.id})
    return True


__all__ = ["ACTOR", "EVENT_KIND", "FAILOVER_KEY", "pick_supplier", "try_failover"]
