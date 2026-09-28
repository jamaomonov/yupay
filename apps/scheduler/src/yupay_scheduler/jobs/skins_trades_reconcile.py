"""Follow in-flight CS2 skin purchases every 5 seconds (plan 3a, Task 6).

A skin offer reaches the customer in about a minute and waits 30 minutes for them to
accept it, so the order page has to move with it: «покупаем» → «обмен отправлен» →
«получено». Each due task goes through ``process_webhook_update`` in its own
transaction (one bad task never stops the rest); the next look is 5 s away while
Waxpeer is buying and 10 s once the offer is out (``skin_sweeps``). The general
``waxpeer_reconcile`` sweep skips these tasks.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.service import process_webhook_update, schedule_next_check
from yupay.modules.fulfillment.skin_sweeps import due_skin_task_ids, skin_recheck_seconds

log = get_logger("yupay.scheduler.skins_trades_reconcile")

_JOB_ID = "fulfillment.skins_trades_reconcile"
_INTERVAL_SECONDS = 5


async def _reconcile_one(task_id: str) -> None:
    factory = get_session_factory()
    try:
        async with factory() as session, session.begin():
            await process_webhook_update(session, task_id=task_id)
    finally:
        async with factory() as session, session.begin():
            seconds = await skin_recheck_seconds(session, task_id=task_id)
            await schedule_next_check(session, task_id=task_id, seconds=seconds)


async def run_skins_trades_reconcile() -> None:
    """One tick: every due skin task, each isolated."""
    async with get_session_factory()() as session:
        task_ids = await due_skin_task_ids(session)
    if not task_ids:
        return
    failed = 0
    for task_id in task_ids:
        try:
            await _reconcile_one(task_id)
        except Exception as exc:  # noqa: BLE001 -- one bad task must never abort the sweep
            failed += 1
            log.warning("skins_trades_reconcile.task_failed", task_id=task_id, error=str(exc))
    log.info("skins_trades_reconcile.tick", checked=len(task_ids), failed=failed)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler."""
    scheduler.add_job(
        run_skins_trades_reconcile,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("skins_trades_reconcile.registered", interval_seconds=_INTERVAL_SECONDS)
