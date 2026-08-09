"""Periodically pull supplier stock for voucher SKUs.

Gift cards and vouchers are finite: G2B holds a real pile of codes per product
and reports what is left. Game top-ups are minted on demand, so they are not
touched — only mappings with ``kind='voucher'`` are swept.

Runs on the same interval as the price refresh, for the same reason: both read
the supplier's view of a product, and there is no value in learning that a code
costs more while still believing there are codes.

Each SKU is written in its own transaction inside
``integrations.stock_refresh.refresh_voucher_stock`` — one bad product id never
blocks the rest. A SKU crossing into out-of-stock raises one Telegram alert on
the transition, not on every tick.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.integrations.stock_refresh import refresh_voucher_stock

log = get_logger("yupay.scheduler.refresh_voucher_stock")

_JOB_ID = "integrations.refresh_voucher_stock"


async def run_refresh_voucher_stock() -> None:
    """One scheduler tick. Logs the summary so ops can grep the run history
    without touching the DB."""
    report = await refresh_voucher_stock()
    log.info(
        "integrations.refresh_voucher_stock.tick",
        checked=report.checked,
        updated=report.updated,
        went_out_of_stock=report.went_out_of_stock,
        errors=report.errors,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().price_refresh_interval_minutes))
    scheduler.add_job(
        run_refresh_voucher_stock,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=_JOB_ID, interval_minutes=minutes)
