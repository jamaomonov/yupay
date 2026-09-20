"""Scheduler entrypoint.

Run as: ``python -m yupay_scheduler.main``.
"""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.logging import configure_logging, get_logger
from yupay.core.observability import init_sentry

# Touch every module's models so SQLAlchemy's metadata has the full graph
# resolved before any query runs. Without this, cross-table FKs (e.g.
# ``orders.user_id → users.id``) raise ``NoReferencedTableError`` because
# the dependent ``users.models`` module never got imported.
from yupay.modules.auth import models as _auth_models  # noqa: F401
from yupay.modules.blog import models as _blog_models  # noqa: F401
from yupay.modules.broadcasts import models as _broadcasts_models  # noqa: F401
from yupay.modules.catalog import models as _catalog_models  # noqa: F401
from yupay.modules.click import models as _click_models  # noqa: F401
from yupay.modules.fulfillment import models as _fulfillment_models  # noqa: F401
from yupay.modules.fulfillment.suppliers.g2b_client import close_g2b_pool
from yupay.modules.fx import models as _fx_models  # noqa: F401
from yupay.modules.integrations import models as _integrations_models  # noqa: F401
from yupay.modules.inventory import models as _inventory_models  # noqa: F401
from yupay.modules.orders import models as _orders_models  # noqa: F401
from yupay.modules.payme import models as _payme_models  # noqa: F401
from yupay.modules.payments import models as _payments_models  # noqa: F401
from yupay.modules.reviews import models as _reviews_models  # noqa: F401
from yupay.modules.sourcing import models as _sourcing_models  # noqa: F401
from yupay.modules.users import models as _users_models  # noqa: F401
from yupay.modules.uzum import models as _uzum_models  # noqa: F401
from yupay.modules.wallet import models as _wallet_models  # noqa: F401

from yupay_scheduler.jobs import (
    affiliate_accrual,
    blog_publish_due,
    broadcast_dispatch,
    bunzy_import,
    catalog_watch,
    click_timeout,
    expire_orders,
    fx_refresh,
    g2b_reconcile,
    gengine_reconcile,
    held_order_refund,
    merchant_feed,
    nova_reconcile,
    payme_timeout,
    purge_evidence,
    purge_sessions,
    recompute_review_stats,
    refresh_supplier_prices,
    refresh_voucher_stock,
    review_reminder,
    stuck_orders,
    sync_supplier_catalog,
    uzum_timeout,
    waxpeer_reconcile,
)

configure_logging()
log = get_logger("yupay.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """Build the AsyncIO scheduler with all production jobs attached.

    New periodic jobs land here — keep the body short by delegating
    registration to each ``jobs/<name>.register(scheduler)`` helper.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    affiliate_accrual.register(scheduler)
    blog_publish_due.register(scheduler)
    broadcast_dispatch.register(scheduler)
    bunzy_import.register(scheduler)
    catalog_watch.register(scheduler)
    click_timeout.register(scheduler)
    expire_orders.register(scheduler)
    fx_refresh.register(scheduler)
    g2b_reconcile.register(scheduler)
    gengine_reconcile.register(scheduler)
    held_order_refund.register(scheduler)
    merchant_feed.register(scheduler)
    nova_reconcile.register(scheduler)
    payme_timeout.register(scheduler)
    purge_evidence.register(scheduler)
    purge_sessions.register(scheduler)
    recompute_review_stats.register(scheduler)
    refresh_supplier_prices.register(scheduler)
    refresh_voucher_stock.register(scheduler)
    review_reminder.register(scheduler)
    stuck_orders.register(scheduler)
    sync_supplier_catalog.register(scheduler)
    uzum_timeout.register(scheduler)
    waxpeer_reconcile.register(scheduler)
    return scheduler


async def run() -> None:
    """Start the scheduler and block until SIGINT/SIGTERM."""
    init_sentry(get_settings(), integrations="none")
    scheduler = build_scheduler()
    scheduler.start()
    log.info("scheduler.started")

    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    # ``wait=False`` because ``wait=True`` is a promise APScheduler cannot
    # keep and we were making it anyway. ``AsyncIOExecutor.shutdown`` says so
    # in its own source — "There is no way to honor wait=True without
    # converting this method into a coroutine method" — and cancels every
    # in-flight coroutine job either way.
    #
    # Draining properly is not available to us either: this container gets
    # Docker's default ten seconds before SIGKILL, and one merchant-feed tick
    # pushes 205 SKUs to Google over minutes. So a deploy landing mid-tick
    # cuts the job, and that is correct — every job here is periodic and
    # re-runnable, and the next tick redoes the work.
    #
    # The honest spelling is `False`. The resulting `CancelledError` is not
    # reported as an error either: `core.observability._is_shutdown_cancellation`
    # drops exactly that event, because an alert that fires on every deploy is
    # an alert nobody reads.
    scheduler.shutdown(wait=False)
    # The G2B jobs share one connection pool for the process lifetime (see
    # ``g2b_client._pool``); the API closes it in its lifespan, this is the
    # same courtesy here.
    await close_g2b_pool()
    log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(run())
