"""Expire stale ``pending_payment`` orders.

Runs every minute. Flips every order whose ``expires_at`` has elapsed to
``expired`` and emits an ``order.expired`` audit event so the admin
dashboard can tell apart abandoned carts from explicitly-cancelled ones.

The expiry guard also runs lazily inside ``get_order_for_actor`` and
``list_orders_for_actor`` — this job exists for the long tail of orders
nobody opens (silent abandonment) and to keep the admin's
``pending_payment`` count honest.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger

# Importing from ``orders.api`` would pull in route registrations, which in
# turn try to register the whole ``api/v1`` router stack — fine in the FastAPI
# process but a circular import here. Reach into ``service`` directly; the
# function is in ``orders.api.__all__`` so this stays inside the module's
# public surface either way.
from yupay.modules.orders.service import expire_stale_orders

log = get_logger("yupay.scheduler.expire_orders")

_JOB_ID = "orders.expire_stale"
_INTERVAL_SECONDS = 60


async def run_expire_stale_orders() -> None:
    """One scheduler tick. Uses its own session/transaction so a failure here
    can't poison a request-scoped session held by the API process."""
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            count = await expire_stale_orders(session)
        if count:
            log.info("orders.expire_stale.flipped", count=count)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_expire_stale_orders,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race on the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("orders.expire_stale.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_expire_stale_orders"]
