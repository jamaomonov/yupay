"""Reconcile in-flight top-ups for a panel vendor (``nova``, ``fzr``).

These vendors charge on create and then leave the order in ``processing``
until it completes or is refunded, so **without a poll a finished order is
never noticed**: the customer watches "в обработке" and the task never leaves
``in_progress``. This sweep only *observes* — nothing here spends money,
because the money left at create time.

One module for both because they are one protocol (ADR-0092). The vendor is a
parameter, so every log event still names whoever produced it:
``nova_reconcile.tick`` stays exactly the event the runbook greps.

Runs every ten seconds per vendor. Each stuck task is reconciled through
``fulfillment.process_webhook_update`` — the same supplier-generic reconciler a
webhook route would call — in its own session and transaction, so one bad task
can never abort the batch.

Idempotent and safe to overlap: the sweep lists only tasks currently
``in_progress`` and due a check, and ``process_webhook_update`` short-circuits
one that already reached a terminal state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger

# Importing from ``fulfillment.api`` would pull in ``routes.py`` -> the whole
# ``api/v1`` router stack (fine inside the FastAPI process, a circular import
# here — see ``expire_orders.py`` for the same trap with ``orders.api``).
# Reach into ``service`` directly; every function is in
# ``fulfillment.api.__all__`` so this stays inside the module's public surface.
from yupay.modules.fulfillment.service import (
    due_reconcile_task_ids,
    process_webhook_update,
    schedule_next_check,
    task_progress_mark,
)

#: Ten seconds, for both vendors. ``due_reconcile_task_ids`` is what keeps
#: that cheap: a task carries ``next_attempt_at``, so a fast tick does not
#: mean every in-flight order is polled every ten seconds.
INTERVAL_SECONDS = 10


async def _list_due_task_ids(slug: str) -> list[str]:
    """That vendor's tasks whose next status check is due.

    Due includes a task nobody has asked about yet — a fresh order carries no
    ``next_attempt_at``.
    """
    factory = get_session_factory()
    async with factory() as session:
        return await due_reconcile_task_ids(session, supplier=slug)


async def reconcile_one(task_id: str) -> None:
    """Reconcile a single task in its own session/transaction.

    A check that **advanced** the task is not deferred: the next step may be
    available right now, so deferring would make it wait a whole cadence for
    nothing.
    """
    factory = get_session_factory()
    advanced = False
    try:
        async with factory() as session, session.begin():
            before = await task_progress_mark(session, task_id=task_id)
            await process_webhook_update(session, task_id=task_id)
            advanced = await task_progress_mark(session, task_id=task_id) != before
    finally:
        if not advanced:
            # Its own transaction, deliberately. Inside the one above it would
            # roll back with the failure it is meant to outlive, leaving the
            # task due again immediately — so a supplier we could not read
            # would be asked again in ten seconds, the opposite of the point.
            async with factory() as session, session.begin():
                await schedule_next_check(session, task_id=task_id)


def make_runner(slug: str) -> Callable[[], Awaitable[None]]:
    """One vendor's tick function.

    Failures are isolated per task — logged (task id + error only, never PII
    like ``player_id``) and skipped — so a single bad row cannot stop the rest
    of the backlog from being swept.
    """
    log = get_logger(f"yupay.scheduler.{slug}_reconcile")
    # Built once rather than f-stringed at each call site: our structured
    # logger takes the event as a positional *name*, and ruff's G004 reads an
    # f-string there as a formatting mistake.
    ev_failed = f"{slug}_reconcile.task_failed"
    ev_tick = f"{slug}_reconcile.tick"

    async def run() -> None:
        task_ids = await _list_due_task_ids(slug)
        if not task_ids:
            return

        reconciled = 0
        failed = 0
        for task_id in task_ids:
            try:
                await reconcile_one(task_id)
            except Exception as exc:  # noqa: BLE001 -- one bad task must never abort the sweep
                failed += 1
                log.warning(ev_failed, task_id=task_id, error=str(exc))
            else:
                reconciled += 1

        log.info(
            ev_tick,
            checked=len(task_ids),
            reconciled=reconciled,
            failed=failed,
        )

    run.__name__ = f"run_{slug}_reconcile"
    return run


def register_panel(scheduler: AsyncIOScheduler, *, slug: str) -> None:
    """Attach one vendor's sweep to a running scheduler. Call once at startup."""
    log = get_logger(f"yupay.scheduler.{slug}_reconcile")
    ev = f"{slug}_reconcile.registered"
    scheduler.add_job(
        make_runner(slug),
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=f"fulfillment.{slug}_reconcile",
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info(ev, interval_seconds=INTERVAL_SECONDS)


__all__ = ["INTERVAL_SECONDS", "make_runner", "reconcile_one", "register_panel"]
