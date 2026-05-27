"""Scheduler entrypoint.

Run as: ``python -m yupay_scheduler.main``.
"""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.logging import configure_logging, get_logger

# Touch every module's models so SQLAlchemy's metadata has the full graph
# resolved before any query runs. Without this, cross-table FKs (e.g.
# ``orders.user_id → users.id``) raise ``NoReferencedTableError`` because
# the dependent ``users.models`` module never got imported.
from yupay.modules.auth import models as _auth_models  # noqa: F401
from yupay.modules.catalog import models as _catalog_models  # noqa: F401
from yupay.modules.fulfillment import models as _fulfillment_models  # noqa: F401
from yupay.modules.fx import models as _fx_models  # noqa: F401
from yupay.modules.integrations import models as _integrations_models  # noqa: F401
from yupay.modules.inventory import models as _inventory_models  # noqa: F401
from yupay.modules.orders import models as _orders_models  # noqa: F401
from yupay.modules.payments import models as _payments_models  # noqa: F401
from yupay.modules.sourcing import models as _sourcing_models  # noqa: F401
from yupay.modules.users import models as _users_models  # noqa: F401
from yupay.modules.wallet import models as _wallet_models  # noqa: F401

from yupay_scheduler.jobs import expire_orders, refresh_supplier_prices

configure_logging()
log = get_logger("yupay.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """Build the AsyncIO scheduler with all production jobs attached.

    New periodic jobs land here — keep the body short by delegating
    registration to each ``jobs/<name>.register(scheduler)`` helper.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    expire_orders.register(scheduler)
    refresh_supplier_prices.register(scheduler)
    return scheduler


async def run() -> None:
    """Start the scheduler and block until SIGINT/SIGTERM."""
    scheduler = build_scheduler()
    scheduler.start()
    log.info("scheduler.started")

    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    scheduler.shutdown(wait=True)
    log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(run())
