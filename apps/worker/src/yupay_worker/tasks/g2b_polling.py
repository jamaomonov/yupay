"""Polling actor for G2B async orders.

Acts as a safety net behind G2B's webhook callbacks: if the webhook never
arrives (callback URL unreachable, transient G2B failure, dev tunnels
flapping), the polling actor will still reconcile the task by calling
``check_status`` through the same code path as the webhook.

Scheduling cadence — exponential backoff (5s, 10s, 30s, 60s, 120s, 300s).
After ``_MAX_ATTEMPTS`` polls without a terminal outcome (~10 minutes wall
time) we mark the task as failed with a clear last_error. That matches
G2B's own behaviour on stuck orders and keeps the admin queue tidy.
"""

from __future__ import annotations

import asyncio

import dramatiq
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.fulfillment import service as fulfillment_svc
from yupay.modules.fulfillment.api import get_task_admin

log = get_logger("yupay.worker.g2b_polling")

# (seconds-until-next-poll) per attempt — attempt 0 fires immediately after
# fulfill() returns in_progress, attempt 1 picks 10s later, etc.
_SCHEDULE_MS = [5_000, 10_000, 30_000, 60_000, 120_000, 300_000]
_MAX_ATTEMPTS = len(_SCHEDULE_MS)


@dramatiq.actor(
    queue_name="default",
    max_retries=0,  # retry is handled by re-scheduling with delay, not Dramatiq retries.
)
def poll_g2b_task(task_id: str, attempt: int = 0) -> None:
    """Reconcile a single G2B task. Reschedules itself if still pending."""
    asyncio.run(_run(task_id=task_id, attempt=attempt))


async def _run(*, task_id: str, attempt: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        try:
            task = await get_task_admin(session, task_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("g2b.polling.task_missing", task_id=task_id, error=str(exc))
            return

        if task.status in ("succeeded", "failed", "cancelled"):
            log.info(
                "g2b.polling.terminal",
                task_id=task_id,
                status=task.status,
                attempt=attempt,
            )
            return

        updated = await fulfillment_svc.process_webhook_update(session, task_id=task_id)
        await session.commit()

        if updated.status in ("succeeded", "failed", "cancelled"):
            log.info(
                "g2b.polling.reconciled",
                task_id=task_id,
                status=updated.status,
                attempt=attempt,
            )
            return

        next_attempt = attempt + 1
        if next_attempt >= _MAX_ATTEMPTS:
            updated.status = "failed"
            updated.last_error = "g2b polling timeout: no terminal status after retries"
            await session.commit()
            log.warning(
                "g2b.polling.timeout",
                task_id=task_id,
                attempts=next_attempt,
            )
            return

        delay = _SCHEDULE_MS[next_attempt]
        log.info(
            "g2b.polling.reschedule",
            task_id=task_id,
            attempt=next_attempt,
            delay_ms=delay,
        )
        poll_g2b_task.send_with_options(args=(task_id, next_attempt), delay=delay)


__all__ = ["poll_g2b_task"]
