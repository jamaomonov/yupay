"""Is an order **stopped without having finished failing**?

The saga has one soft failure. When a supplier refuses because *our* balance
with them is short, :func:`service._apply_failure` fails the task — so it
lands in the admin inbox and raises the low-balance alert — and deliberately
leaves the order item ``in_progress``, so the storefront keeps saying
"обработка" while an operator tops up and retries. That is the right answer
for a buyer with a support chat, and it is the reason a merchant order could
sit at ``status: "fulfilling", failure_reason: null`` indefinitely, byte for
byte identical to one placed thirty seconds ago (M3b Task 4).

This module answers the one question that state raises, and nothing else.

## Why the fact is derived and not stored

A stall has to **clear itself** on every route out of it: the operator tops up
and the retry succeeds, the retry fails terminally instead, the task is
cancelled, an operator delivers by hand, support closes the order. A stored
marker would need every one of those sites to remember to clear it, and the
one that forgot would publish "still coming" about an order that had finished
— which is worse than the silence it replaced, because a machine acts on it.

Derived, there is nothing to forget: every one of those transitions already
moves the task off ``failed``, the item off a non-terminal state, or both,
because that is what ending a line *is*. So no column, no migration, and no
new write site anywhere on the fulfilment path — this module only reads.

## The shape, and why it is the shape rather than the error string

The predicate is "a task of this order has stopped while the item it was
fulfilling has not". It deliberately does **not** test
``last_error == "supplier_low_balance"``.

Six sites in ``service.py`` write ``task.status = "failed"``; five of them set
``item.fulfillment_state = "failed"`` in the same breath, and the sixth is the
low-balance branch, which writes ``in_progress``. So the shape has exactly one
producer today either way — but if a second soft failure is ever added, or a
bug leaves a task failed over a live item, that order really is stalled and
saying so is right. Matching the sentinel would have published silence for it.

The value the caller derives from this never names the cause. That *we* ran
out of balance at a named supplier is a fact about our supplier funding: a
reseller who could read it off the API would learn which of our suppliers is
short of money, which is the same leak that keeps ``SPENT`` and ``UNKNOWN``
out of ``failure_reason``. It stays on the task, in the admin inbox and in the
ops alert, where the person who acts on it looks.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import OrderItem

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.orders.models import Order

#: Item states that mean "this line is still open". The same three
#: ``ix_order_items_state_active`` is filtered on (migration 0006), and the
#: complement of the terminal set ``delivered`` / ``failed`` / ``refunded``.
#: Spelled as the open set rather than as the terminal one on purpose: a new
#: state added to ``ck_order_items_state`` is far more likely to be another
#: in-flight step than another ending, and the safe default for an unknown one
#: is "not stalled", which is what excluding it gives.
UNSETTLED_ITEM_STATES: Final[frozenset[str]] = frozenset({"pending", "reserved", "in_progress"})


async def stalled_order_ids(db: AsyncSession, *, orders: Sequence[Order]) -> set[str]:
    """Which of these orders have a task stopped over an item that is still open?

    **The predicate, in the one shape both callers use.** M3c Task 3 gave it a
    second caller — the admin order list, which renders the same fact beside
    the status an operator reads — and a list endpoint may not ask one question
    per row (AGENTS.md §10). So the batch is the definition and
    :func:`order_is_stalled` is the one-element case, rather than two
    statements that would drift about what "stalled" means.

    **It pays for the database only when the answer can be yes.** Every item of
    a delivered or terminally failed order is in a terminal state, so no task
    of it can be a stalled one, and such orders are dropped before the read —
    which matters on the endpoint resellers are told to poll, and it means a
    page of settled orders costs nothing at all. The candidates cost one
    indexed read on ``ix_fulfillment_tasks_order_id``, over the handful of rows
    an order can have. No index was added: that one has existed since migration
    0008 and is the whole access path.

    The in-memory half is the same condition as the SQL half, and is here
    rather than at either call site so there is one spelling of it.

    Args:
        db: Session. The caller owns the transaction.
        orders: The orders to test, **with their items loaded** — they are, on
            every path that reaches this: ``Order.items`` is ``lazy="selectin"``.

    Returns:
        The ids of those orders with at least one ``failed`` fulfilment task
        whose item is still open. Never contains an id that was not asked for.
    """
    candidates = [
        order.id
        for order in orders
        if any(item.fulfillment_state in UNSETTLED_ITEM_STATES for item in order.items)
    ]
    if not candidates:
        return set()
    rows = (
        await db.execute(
            select(FulfillmentTask.order_id)
            .join(OrderItem, OrderItem.id == FulfillmentTask.order_item_id)
            .where(
                FulfillmentTask.order_id.in_(candidates),
                FulfillmentTask.status == "failed",
                OrderItem.fulfillment_state.in_(UNSETTLED_ITEM_STATES),
            )
            .distinct()
        )
    ).scalars()
    return set(rows)


async def order_is_stalled(db: AsyncSession, *, order: Order) -> bool:
    """Has a task of this order stopped while its item is still open?

    A one-element :func:`stalled_order_ids`. It stays a named function because
    it is what the merchant order read asks, and reading ``order.id in {...}``
    at that call site would put the batch's shape into a place that only ever
    has one order.

    Args:
        db: Session. The caller owns the transaction.
        order: The order, with its items loaded.

    Returns:
        ``True`` when at least one of this order's fulfilment tasks is
        ``failed`` while the item it was fulfilling is still open.
    """
    return order.id in await stalled_order_ids(db, orders=[order])


__all__ = ["UNSETTLED_ITEM_STATES", "order_is_stalled", "stalled_order_ids"]
