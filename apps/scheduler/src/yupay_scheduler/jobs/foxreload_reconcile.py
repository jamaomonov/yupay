"""Reconcile in-flight FoxReload Steam top-ups (ADR-0107).

Their order is paid, then ``processing``, then ``completed`` or ``failed`` →
``refunded``. The sweep reads each in-flight order through the adapter's
``check_status`` (which also pays an order whose ``pay`` answer was lost).

It is the panel vendors' sweep, run for ``foxreload``: a 10 s tick over tasks
*due* a check (new ones at once, older ones on the shared backoff), so the
``order.completed`` webhook — which only marks a task due — lands within one
tick. Failed and refunded orders send no event; this sweep finds those on its
own. Their edge allows 5 requests a second per IP, far above this.
"""

from __future__ import annotations

# Prime ``yupay.api.v1`` before the settle path imports it (see waxpeer_reconcile).
import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from yupay_scheduler.jobs.panel_reconcile import register_panel

SLUG = "foxreload"


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job (``fulfillment.foxreload_reconcile``). Call once at startup."""
    register_panel(scheduler, slug=SLUG)
