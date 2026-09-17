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
from yupay.modules.fulfillment.service import list_tasks_admin, process_webhook_update

log = get_logger("yupay.scheduler.nova_reconcile")

_JOB_ID = "fulfillment.nova_reconcile"
_INTERVAL_SECONDS = 60
_SUPPLIER = "nova"
_STATUS = "in_progress"
_PAGE_SIZE = 100
# Ceiling on how many pages one tick will walk (100 * 50 = 5,000 tasks). A
# real backlog that size means something upstream is badly broken; log it
# loudly rather than silently truncating the sweep to "whatever fit".
_MAX_PAGES = 50


async def _list_stuck_task_ids() -> list[str]:
    """Page through every ``in_progress`` nova task, collecting just the
    ids. One read-only session for the whole listing pass — the tasks
    themselves are reconciled later, each in its own session."""
    factory = get_session_factory()
    task_ids: list[str] = []
    async with factory() as session:
        offset = 0
        for _page in range(_MAX_PAGES):
            tasks, total = await list_tasks_admin(
                session,
                supplier=_SUPPLIER,
                status_filter=_STATUS,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            if not tasks:
                break
            task_ids.extend(t.id for t in tasks)
            offset += len(tasks)
            if offset >= total:
                break
        else:
            log.warning(
                "nova_reconcile.page_limit_hit",
                pages=_MAX_PAGES,
                collected=len(task_ids),
            )
    return task_ids


async def _reconcile_one(task_id: str) -> None:
    """Reconcile a single task in its own session/transaction."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await process_webhook_update(session, task_id=task_id)


async def run_nova_reconcile() -> None:
    """One scheduler tick: reconcile every in_progress nova task.

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
