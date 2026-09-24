"""Reconcile in-flight FazerCards top-ups.

FazerCards has a webhook, and we receive it — but it is not the only path and
must not be the only path. Their delivery gives up after three retries, and
they disable the hook entirely after fifty consecutive failures; a sweep is
what makes a lost event cost latency instead of an order.

Everything about the sweep is in ``panel_reconcile``, which NOVA shares. This
file exists so the scheduler's registration list reads as one line per
supplier, the way it already does for the other four.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from yupay_scheduler.jobs.panel_reconcile import make_runner, register_panel

SUPPLIER = "fzr"

#: Exposed for tests and for a manual one-off run, mirroring the other jobs.
run_fzr_reconcile = make_runner(SUPPLIER)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    register_panel(scheduler, slug=SUPPLIER)
