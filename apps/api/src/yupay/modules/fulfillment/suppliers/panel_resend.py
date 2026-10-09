"""Re-send a panel create that never left us (NOVA, FazerCards).

The panels charge on create, so a create whose answer was lost is parked for adoption
(``panel_adopt``): we search their order list for 30 minutes rather than buy twice. That is
right when the request *may* have arrived, and needlessly slow when it cannot have: a
``ConnectError`` / ``ConnectTimeout`` / ``PoolTimeout`` happens before httpx writes a byte
(``panel_client._NEVER_SENT``). On 2026-10-09 an fzr Likee order sat 30 minutes in
adoption after a ``ConnectError`` and then needed a human, though fzr had never seen it.

So a create that was never sent is sent again, with the **same** idempotency key:

* at once, a few times a few seconds apart, inside the client (``panel_client._request`` with
  ``resend_unsent=True``, which every create passes);
* then from every status poll (:func:`resend_from_status`) for
  :data:`NOT_SENT_WINDOW_MINUTES`; past that the task fails with nothing spent
  (``RETURNED``) — true by construction, because every attempt failed before sending.

Two guards make a second purchase impossible here, not merely unlikely:

1. Only a never-sent failure is re-sent. The moment one attempt *might* have landed, the
   task carries ``<slug>_create_unresolved`` and the status poll goes to adoption, never to
   another create (:func:`should_resend`).
2. The key is the one the lost attempt carried. FazerCards answers a reused key with the
   original order (measured 2026-09-24); NOVA answers 409, which is graded undecided —
   in neither case is a second order placed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.panel_resend")

#: How long the status poll keeps re-sending a never-sent create.
NOT_SENT_WINDOW_MINUTES = 30


class _Fulfiller(Protocol):
    async def fulfill(
        self, *, db: AsyncSession, order: Order, item: OrderItem, idempotency_key: str
    ) -> FulfillResult: ...


def not_sent_key(slug: str) -> str:
    """Metadata key: the last create never reached the panel."""
    return f"{slug}_create_not_sent"


def unresolved_key(slug: str) -> str:
    """Metadata key: a create may have reached the panel and its answer was lost."""
    return f"{slug}_create_unresolved"


def not_sent_result(slug: str, exc: Exception) -> FulfillResult:
    """The create never reached the panel: in flight, id-less, nothing spent yet."""
    return FulfillResult(
        outcome="in_progress",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={"supplier": slug, not_sent_key(slug): str(exc)[:200]},
        money_outcome=None,
    )


def should_resend(meta: dict[str, Any], *, slug: str) -> bool:
    """An id-less task whose every create failed before sending."""
    return not_sent_key(slug) in meta and unresolved_key(slug) not in meta


async def resend_from_status(
    fulfiller: _Fulfiller, db: AsyncSession, task: FulfillmentTask, *, slug: str
) -> FulfillStatus:
    """Send the never-sent create again from a status poll, with the task's own key."""
    # Lazy: ``fulfillment.service`` imports the supplier registry, which imports this.
    from yupay.modules.fulfillment.service import idempotency_key_for
    from yupay.modules.orders.models import Order, OrderItem

    if now() - task.created_at > timedelta(minutes=NOT_SENT_WINDOW_MINUTES):
        return FulfillStatus(
            outcome="failed",
            artifact_kind=None,
            artifact=None,
            error=(
                f"{slug} could not be reached for {NOT_SENT_WINDOW_MINUTES} minutes; "
                "no request ever reached them, so nothing was spent — safe to retry"
            ),
            money_outcome=MoneyOutcome.RETURNED,
        )
    item = await db.get(OrderItem, task.order_item_id)
    order = await db.get(Order, task.order_id)
    if item is None or order is None:  # pragma: no cover - FK
        return FulfillStatus(
            outcome="failed",
            artifact_kind=None,
            artifact=None,
            error="order line is gone",
            money_outcome=MoneyOutcome.RETURNED,
        )
    try:
        result = await fulfiller.fulfill(
            db=db, order=order, item=item, idempotency_key=idempotency_key_for(task)
        )
    except FulfillerError as exc:
        # A refusal is a status, not a raise: the reconciler fails the task on a failed
        # status and only logs a raise (see ``_adopt_or_wait``).
        return FulfillStatus(
            outcome="failed",
            artifact_kind=None,
            artifact=None,
            error=str(exc)[:500],
            money_outcome=exc.money_outcome,
        )
    extra = dict(result.extra_metadata or {})
    if result.external_order_id:
        # The reconciler merges metadata but does not move ids into the column; the
        # adapter's ``check_status`` reads this key, as it does after an adoption.
        extra[f"{slug}_order_id"] = result.external_order_id
    log.info(
        "panel.create_resent_from_status", supplier=slug, outcome=result.outcome, task_id=task.id
    )
    return FulfillStatus(
        outcome=result.outcome,
        artifact_kind=result.artifact_kind,
        artifact=result.artifact,
        error=result.error,
        extra_metadata=extra,
        money_outcome=result.money_outcome,
    )


__all__ = [
    "NOT_SENT_WINDOW_MINUTES",
    "not_sent_key",
    "not_sent_result",
    "resend_from_status",
    "should_resend",
    "unresolved_key",
]
