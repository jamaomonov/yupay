"""Reconcile in-flight G2B game top-ups.

G2B *does* send a webhook on terminal status, but it fires exactly once with a
single retry and a 10s timeout (see ``docs/g2b-intergation.md``) — a cold
start, a redeploy, or a transient 5xx on our side loses it permanently and the
task is then stranded in ``in_progress`` forever. A periodic sweep is the fix:
it reconciles *any* stuck task, including ones a lost webhook would never have
notified us about. This is the exact gap ``waxpeer_reconcile`` already closes for
the webhook-less Waxpeer flow; G2B needs the same periodic sweep.

Runs every 60 seconds. Each stuck task is reconciled through
``fulfillment.process_webhook_update`` — the same supplier-generic reconciler
the webhook route calls, which re-verifies the order via ``POST
/games/order/status`` before mutating state — in its **own** session/
transaction, so one bad task can never abort the batch.

Idempotent + safe to overlap: ``process_webhook_update`` short-circuits a task
that already reached a terminal state, and this sweep only ever lists tasks that
are *currently* ``in_progress`` — once reconciled to ``succeeded``/``failed`` a
task drops out of the list. ``max_instances=1`` additionally stops two ticks of
this job from running at once. Mirrors ``waxpeer_reconcile`` deliberately — keep
the two in sync.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger

# Reach into ``service`` directly rather than ``fulfillment.api`` to avoid
# pulling in ``routes.py`` -> the whole ``api/v1`` router stack (a circular
# import here — same trap ``waxpeer_reconcile`` / ``expire_orders`` document).
from yupay.modules.fulfillment.service import list_tasks_admin, process_webhook_update

log = get_logger("yupay.scheduler.g2b_reconcile")

_JOB_ID = "fulfillment.g2b_reconcile"
_INTERVAL_SECONDS = 60
_SUPPLIER = "g2b"
_STATUS = "in_progress"
_PAGE_SIZE = 100
# Ceiling on how many pages one tick will walk (100 * 50 = 5,000 tasks). A real
# backlog that size means something upstream is badly broken; log it loudly
# rather than silently truncating the sweep to "whatever fit".
_MAX_PAGES = 50


async def _list_stuck_task_ids() -> list[str]:
    """Page through every ``in_progress`` g2b task, collecting just the ids.
    One read-only session for the whole listing pass — the tasks themselves are
    reconciled later, each in its own session."""
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
                "g2b_reconcile.page_limit_hit",
                pages=_MAX_PAGES,
                collected=len(task_ids),
            )
    return task_ids


async def _reconcile_one(task_id: str) -> None:
    """Reconcile a single task in its own session/transaction."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await process_webhook_update(session, task_id=task_id)


async def run_g2b_reconcile() -> None:
    """One scheduler tick: reconcile every in_progress g2b task.

    Failures are isolated per task — logged (task id + error only, never PII
    like ``player_id``) and skipped — so a single bad row can't stop the rest of
    the backlog from being swept.
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
            log.warning("g2b_reconcile.task_failed", task_id=task_id, error=str(exc))
        else:
            reconciled += 1

    log.info(
        "g2b_reconcile.tick",
        checked=len(task_ids),
        reconciled=reconciled,
        failed=failed,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_g2b_reconcile,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("g2b_reconcile.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_g2b_reconcile"]
