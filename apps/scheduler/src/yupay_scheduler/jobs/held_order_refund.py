"""Auto-refund orders held for review past their deadline (ADR-0063).

``orders.risk.hold_for_review`` puts a paid catalog order on hold and alerts
an operator to decide: release to fulfilment or refund by hand. Nothing
enforced a deadline on that decision — an alert that is missed (or a hold
nobody gets to before shift change) could sit forever, holding a customer's
money on an order that is never going anywhere. ``risk_hold_auto_refund_hours``
(default 24; ``0`` disables) is that deadline, and this job is what makes it
real.

The selection query, the refund itself, and the per-order failure isolation
all live in ``orders.risk.auto_refund_expired_holds`` — a plain service
function, tested directly from the api test suite the same way
``precharge_veto`` and ``review_reason`` are — so this file stays a thin
scheduler wrapper, the pattern every job in this directory uses.

Runs every 15 minutes and loops the service call within one tick until a
batch comes back under ``_BATCH_LIMIT``, so a backlog bigger than one batch
still drains in a single tick instead of trickling out one batch per
interval. Each order the service function refunds commits its own work
immediately (see its docstring), so looping here never risks losing an
earlier batch's refunds to a later failure.

Importing ``yupay.api.v1`` first avoids the same ``payments.service`` <->
``wallet.routes`` <-> ``api.v1`` cold-import cycle ``payme_timeout.py``
documents in detail — ``auto_refund_expired_holds`` reaches into
``payments.service.refund_admin``, which carries the identical trap.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.orders.risk import auto_refund_expired_holds

log = get_logger("yupay.scheduler.held_order_refund")

_JOB_ID = "orders.auto_refund_held"
_INTERVAL_MINUTES = 15
_BATCH_LIMIT = 50


async def run_held_order_refund() -> None:
    """One scheduler tick: refund every held order past its deadline.

    A single session for the whole tick — ``auto_refund_expired_holds``
    commits per refunded order internally, and isolates per-order failures
    with its own rollback, so sharing one session across batches (rather than
    the own-session-per-item style the acquirer timeout jobs use) is safe
    here.
    """
    factory = get_session_factory()
    total = 0
    async with factory() as session:
        while True:
            n = await auto_refund_expired_holds(session, limit=_BATCH_LIMIT)
            total += n
            if n < _BATCH_LIMIT:
                break
    if total:
        log.info("held_order_refund.tick", refunded=total)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_held_order_refund,
        trigger="interval",
        minutes=_INTERVAL_MINUTES,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("held_order_refund.registered", interval_minutes=_INTERVAL_MINUTES)


__all__ = ["register", "run_held_order_refund"]
