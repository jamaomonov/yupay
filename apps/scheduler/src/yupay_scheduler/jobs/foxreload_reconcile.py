"""Reconcile in-flight FoxReload Steam top-ups (ADR-0107).

Their order is paid, then ``processing``, then ``completed`` or ``failed`` →
``refunded``. They offer webhooks, but none is registered: a sweep self-heals
across restarts and needs no public endpoint, the same reasoning as
``waxpeer_reconcile``. An order still unpaid when the sweep reads it is paid
here (``FoxreloadFulfiller.check_status``), so a ``pay`` whose answer was lost
is finished rather than abandoned.

Every 60 s, each task in its own session, through
``fulfillment.process_webhook_update`` — one bad task never aborts the batch.
Their edge allows 5 requests a second per IP; a backlog of a few dozen is
well inside that.
"""

from __future__ import annotations

# Prime ``yupay.api.v1`` before the settle path imports it (see waxpeer_reconcile).
import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.service import list_tasks_admin, process_webhook_update

log = get_logger("yupay.scheduler.foxreload_reconcile")

_JOB_ID = "fulfillment.foxreload_reconcile"
_INTERVAL_SECONDS = 60
_SUPPLIER = "foxreload"
_STATUS = "in_progress"
_PAGE_SIZE = 100
_MAX_PAGES = 50


async def _list_stuck_task_ids() -> list[str]:
    """Every ``in_progress`` foxreload task id, read in one session."""
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
                "foxreload_reconcile.page_limit_hit", pages=_MAX_PAGES, collected=len(task_ids)
            )
    return task_ids


async def _reconcile_one(task_id: str) -> None:
    """Reconcile a single task in its own session/transaction."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await process_webhook_update(session, task_id=task_id)


async def run_foxreload_reconcile() -> None:
    """One tick: reconcile every in_progress foxreload task (ids only in logs)."""
    task_ids = await _list_stuck_task_ids()
    if not task_ids:
        return
    reconciled = failed = 0
    for task_id in task_ids:
        try:
            await _reconcile_one(task_id)
        except Exception as exc:  # noqa: BLE001 -- one bad task must never abort the sweep
            failed += 1
            log.warning("foxreload_reconcile.task_failed", task_id=task_id, error=str(exc))
        else:
            reconciled += 1
    log.info(
        "foxreload_reconcile.tick", checked=len(task_ids), reconciled=reconciled, failed=failed
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job. Safe to call once at startup."""
    scheduler.add_job(
        run_foxreload_reconcile,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("foxreload_reconcile.registered", interval_seconds=_INTERVAL_SECONDS)
