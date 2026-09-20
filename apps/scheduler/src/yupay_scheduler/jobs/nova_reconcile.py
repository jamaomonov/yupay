"""Reconcile in-flight NOVA top-ups.

NOVA has no webhook. An order is charged on create and then sits in
``processing`` until it completes or is refunded, so without a poll a finished
order is never noticed: the customer watches "в обработке" and the task never
leaves ``in_progress``. Unlike the G-Engine sweep, this one only *observes* —
nothing here spends money, because NOVA takes it at create time.

Runs every 60 seconds. Each stuck task is reconciled through
``fulfillment.process_webhook_update`` — the same supplier-generic reconciler a
real webhook route would call — in its own session and transaction, so one bad
task can never abort the batch.

Idempotent and safe to overlap: the sweep lists only tasks that are currently
``in_progress``, and ``process_webhook_update`` short-circuits one that already
reached a terminal state.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger

# Importing from ``fulfillment.api`` would pull in ``routes.py`` -> the whole
# ``api/v1`` router stack (fine inside the FastAPI process, a circular import
# here — see ``expire_orders.py`` for the same trap with ``orders.api``).
# Reach into ``service`` directly; both functions are in
# ``fulfillment.api.__all__`` so this stays inside the module's public surface.
from yupay.modules.fulfillment.service import (
    due_reconcile_task_ids,
    process_webhook_update,
    schedule_next_check,
    task_progress_mark,
)

log = get_logger("yupay.scheduler.nova_reconcile")

_JOB_ID = "fulfillment.nova_reconcile"
_INTERVAL_SECONDS = 10
_SUPPLIER = "nova"
_STATUS = "in_progress"


async def _list_stuck_task_ids() -> list[str]:
    """The nova tasks whose next status check is due.

    Due includes a task nobody has asked about yet — a fresh order carries no
    ``next_attempt_at`` — which is what lets this tick every ten seconds
    without polling every in-flight order that often.
    """
    factory = get_session_factory()
    async with factory() as session:
        return await due_reconcile_task_ids(session, supplier=_SUPPLIER)


async def _reconcile_one(task_id: str) -> None:
    """Reconcile a single task in its own session/transaction.

    A check that **advanced** the task is not deferred: the next step may be
    available right now, and for G-Engine it always is — the tick that sees
    ``verified`` banks the pay intent and spends nothing, so deferring here
    would make the payment itself wait for the cadence.
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


async def run_nova_reconcile() -> None:
    """One scheduler tick: reconcile every in_progress nova task.

    Failures are isolated per task — logged (task id + error only, never
    PII like ``player_id``) and skipped — so a single bad row can't stop
    the rest of the backlog from being swept.
    """
    task_ids = await _list_stuck_task_ids()
    if not task_ids:
        return

    reconciled = 0
    failed = 0
    for task_id in task_ids:
        try:
            await _reconcile_one(task_id)
        except Exception as exc:  # noqa: BLE001 -- one bad task must never abort the sweep
            failed += 1
            log.warning("nova_reconcile.task_failed", task_id=task_id, error=str(exc))
        else:
            reconciled += 1

    log.info(
        "nova_reconcile.tick",
        checked=len(task_ids),
        reconciled=reconciled,
        failed=failed,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_nova_reconcile,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("nova_reconcile.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_nova_reconcile"]
