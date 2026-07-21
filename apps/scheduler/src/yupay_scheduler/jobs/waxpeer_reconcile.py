"""Reconcile in-flight Waxpeer top-ups.

Waxpeer has no webhook: ``fulfill()`` can come back ``in_progress`` (status
``created``/``sending``) and nothing will ever call back to move the task
forward. A dramatiq self-reschedule (the pattern ``poll_g2b_task`` uses) was
considered and rejected — that actor is only ever kicked off by G2B's
webhook arriving, and Waxpeer has none to kick it. A periodic sweep also
self-heals: it reconciles *any* stuck task, including ones that predate a
scheduler restart, not just ones it personally scheduled a follow-up for.

Runs every 60 seconds. Each stuck task is reconciled through
``fulfillment.process_webhook_update`` — the exact same supplier-generic
reconciler a real webhook route would call — in its **own** session/
transaction, so one bad task (a transient DB hiccup, a supplier surprise)
can never abort the batch and leave the rest of the backlog stuck too.

Idempotent + safe to overlap: ``process_webhook_update`` short-circuits a
task that already reached a terminal state (see ``fulfillment.service``),
and this sweep only ever lists tasks that are *currently* ``in_progress`` —
once a task is reconciled to ``succeeded``/``failed`` it drops out of that
list, so a second, later sweep (or a slow first sweep whose effects are
already committed) simply never looks at it again. ``max_instances=1`` below
additionally stops two ticks of *this* job from literally running at once;
what is not guarded against — same as ``poll_g2b_task`` — is two *genuinely
concurrent* writers racing the same task row (e.g. a sweep tick together
with a hypothetical future webhook), which is a pre-existing property of
``process_webhook_update``, not something introduced here.
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

log = get_logger("yupay.scheduler.waxpeer_reconcile")

_JOB_ID = "fulfillment.waxpeer_reconcile"
_INTERVAL_SECONDS = 60
_SUPPLIER = "waxpeer"
_STATUS = "in_progress"
_PAGE_SIZE = 100
# Ceiling on how many pages one tick will walk (100 * 50 = 5,000 tasks). A
# real backlog that size means something upstream is badly broken; log it
# loudly rather than silently truncating the sweep to "whatever fit".
_MAX_PAGES = 50


async def _list_stuck_task_ids() -> list[str]:
    """Page through every ``in_progress`` waxpeer task, collecting just the
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
                "waxpeer_reconcile.page_limit_hit",
                pages=_MAX_PAGES,
                collected=len(task_ids),
            )
    return task_ids


async def _reconcile_one(task_id: str) -> None:
    """Reconcile a single task in its own session/transaction."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await process_webhook_update(session, task_id=task_id)


async def run_waxpeer_reconcile() -> None:
    """One scheduler tick: reconcile every in_progress waxpeer task.

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
            log.warning("waxpeer_reconcile.task_failed", task_id=task_id, error=str(exc))
        else:
            reconciled += 1

    log.info(
        "waxpeer_reconcile.tick",
        checked=len(task_ids),
        reconciled=reconciled,
        failed=failed,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_waxpeer_reconcile,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("waxpeer_reconcile.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_waxpeer_reconcile"]
