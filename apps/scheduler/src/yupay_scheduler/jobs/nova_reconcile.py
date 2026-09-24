"""Reconcile in-flight NOVA top-ups.

NOVA has no webhook. An order is charged on create and then sits in
``processing`` until it completes or is refunded, so without a poll a finished
order is never noticed: the customer watches "в обработке" and the task never
leaves ``in_progress``. Unlike the G-Engine sweep, this one only *observes* —
nothing here spends money, because NOVA takes it at create time.

The sweep itself lives in ``panel_reconcile``, shared with FazerCards: they
are one protocol (ADR-0092) and the two files were identical but for a slug.
Every log event still reads ``nova_reconcile.*``, which is what the runbook
greps.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from yupay_scheduler.jobs.panel_reconcile import make_runner, register_panel

SUPPLIER = "nova"

#: Kept as a module-level name: it was the job's entry point before the split
#: and a one-off manual run still reaches for it.
run_nova_reconcile = make_runner(SUPPLIER)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    register_panel(scheduler, slug=SUPPLIER)
