"""Pull the supplier catalogue in, so the hourly re-price has something new to say.

``refresh_supplier_prices`` does not call G2B. It copies
``supplier_catalog_cache.unit_price`` onto the SKU — its own history rows name
that as the source. The cache was refreshed only by an admin pressing "Синхр.
каталог", so the price job spent every hour faithfully re-copying whatever
snapshot was last taken by hand.

On production that showed up as ``checked=175, moved=0`` eight hours running
while G2B's price for 1000 Robux had in fact moved: the cache was twelve days
old, and the SKU only re-priced two minutes after somebody synced it manually.

So the sync runs on its own now, on the same period as the price refresh and a
minute ahead of it, which is the order that makes "воркер обновляет цены
каждый час" true rather than merely repetitive.

Originally G2B-only; NOVA and G-Engine joined once ``catalog_sync.py`` grew a
sync for each (see that module and ``catalog_sync_nova.py`` /
``catalog_sync_gengine.py``). Each supplier gets its own session and its own
``try``/``except`` here — the same reasoning ``run_catalog_sync`` documents
for why an unknown supplier is the only thing that's allowed to raise: a NOVA
outage must not cost G2B or G-Engine their tick, and vice versa.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.integrations.catalog_sync import SYNCABLE_SUPPLIERS, run_catalog_sync

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.sync_supplier_catalog")

_JOB_ID = "integrations.sync_supplier_catalog"

#: Stable order rather than iterating ``SYNCABLE_SUPPLIERS`` (a frozenset)
#: directly, so log output — and the order suppliers hit their upstream APIs
#: in — doesn't vary run to run. Sorted so a new entry in
#: ``catalog_sync.SYNCABLE_SUPPLIERS`` is picked up here without also having
#: to edit this tuple.
_SUPPLIERS: tuple[str, ...] = tuple(sorted(SYNCABLE_SUPPLIERS))


async def run_sync_supplier_catalog() -> None:
    """One tick per supplier. Never raises: one supplier's outage — or a bug
    in its sync — must not cost the others their tick, or stop the scheduler."""
    factory = get_session_factory()
    for supplier in _SUPPLIERS:
        try:
            async with factory() as session:
                report = await run_catalog_sync(session, supplier_slug=supplier)
                await session.commit()
        except Exception as exc:  # noqa: BLE001 -- one supplier's crash must not take the others down
            log.warning(
                "integrations.sync_supplier_catalog.tick_failed",
                supplier=supplier,
                error=str(exc),
            )
            continue
        log.info(
            "integrations.sync_supplier_catalog.tick",
            supplier=supplier,
            vouchers=report.vouchers,
            games=report.games,
            mapped_vouchers=report.mapped_vouchers,
            missing_upstream=report.missing_upstream,
            error=report.error,
        )


def register(scheduler: AsyncIOScheduler) -> None:
    minutes = max(1, int(get_settings().price_refresh_interval_minutes))
    scheduler.add_job(
        run_sync_supplier_catalog,
        trigger="interval",
        minutes=minutes,
        id=_JOB_ID,
        # 30s ahead of `refresh_supplier_prices` (which starts at +90s) so each
        # re-price reads a catalogue fetched moments earlier rather than an
        # hour-old one.
        next_run_time=first_run_after(60),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=_JOB_ID, interval_minutes=minutes)
