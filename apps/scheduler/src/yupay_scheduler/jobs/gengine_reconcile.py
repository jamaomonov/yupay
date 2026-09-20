"""Reconcile in-flight G-Engine top-ups.

G-Engine has no webhook, and unlike every other supplier its orders are not a
single step. A recharge order walks ``pending → verified → paid → shipped``, and
**we** are what moves it: ``verified`` is the state that opens payment, so a
poll is not just an observation — it is the call that spends the money. Nothing
upstream will ever call back to trigger it.

This job did not exist when the adapter shipped, and the first live Stars order
showed exactly what that costs: created at G-Engine, sat at ``verified`` for
nine hours with one attempt on the clock, our balance untouched and the customer
watching "в обработке". The order was fine; nobody was asking about it.

Runs every 60 seconds. Each stuck task is reconciled through
``fulfillment.process_webhook_update`` — the exact same supplier-generic
reconciler a real webhook route would call — in its **own** session/
transaction, so one bad task (a transient DB hiccup, a supplier surprise)
can never abort the batch and leave the rest of the backlog stuck too.

A task needs several ticks to finish, which is by design: the adapter only
reports success on ``shipped``, never on ``paid``, so a sale is never called
delivered while the supplier is still working on it.

Idempotent + safe to overlap: ``process_webhook_update`` short-circuits a
task that already reached a terminal state (see ``fulfillment.service``),
and this sweep only ever lists tasks that are *currently* ``in_progress`` —
once a task is reconciled to ``succeeded``/``failed`` it drops out of that
list, so a second, later sweep (or a slow first sweep whose effects are
already committed) simply never looks at it again. Paying twice is guarded
further upstream: ``_advance`` only pays a ``verified`` order, and an order
already ``paid`` or ``shipped`` falls through to the read-only branches.
``max_instances=1`` below additionally stops two ticks of *this* job from
literally running at once.
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

log = get_logger("yupay.scheduler.gengine_reconcile")

_JOB_ID = "fulfillment.gengine_reconcile"
_INTERVAL_SECONDS = 10
_SUPPLIER = "gengine"
_STATUS = "in_progress"


async def _list_stuck_task_ids() -> list[str]:
    """The gengine tasks whose next status check is due.

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


async def run_gengine_reconcile() -> None:
    """One scheduler tick: reconcile every in_progress gengine task.

    Failures are isolated per task — logged (task id + error only, never
    PII like ``steam_login``) and skipped — so a single bad row can't stop
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
            log.warning("gengine_reconcile.task_failed", task_id=task_id, error=str(exc))
        else:
            reconciled += 1

    log.info(
        "gengine_reconcile.tick",
        checked=len(task_ids),
        reconciled=reconciled,
        failed=failed,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_gengine_reconcile,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("gengine_reconcile.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_gengine_reconcile"]
