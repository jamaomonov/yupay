"""One FX refresh tick: write history, then report fiat drops.

Scheduler and the admin force-refresh share this so a manual refresh can
trip the kill-switch the same way the 5-minute job does.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import get_settings
from yupay.modules.fx.drop_detect import RateDrop, detect_drops
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.models import FxRate
from yupay.modules.fx.providers.base import Quote


async def latest_history_rates(db: AsyncSession, *, base: str = "USD") -> dict[str, Decimal]:
    """Most recent ``fx_rates`` row per quote (Postgres ``DISTINCT ON``)."""
    stmt = (
        select(FxRate.quote, FxRate.rate)
        .where(FxRate.base == base.upper())
        .distinct(FxRate.quote)
        .order_by(FxRate.quote, FxRate.fetched_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return {str(quote).upper(): rate for quote, rate in rows}


async def refresh_and_detect_drops(
    db: AsyncSession,
) -> tuple[dict[str, Quote], list[RateDrop]]:
    """Refresh the market matrix, then compare against the previous history."""
    settings = get_settings()
    previous = await latest_history_rates(db)
    current = await build_default_service().refresh_all(db)
    drops = detect_drops(
        previous,
        {quote: q.rate for quote, q in current.items()},
        threshold_pct=settings.fx_drop_tripwire_pct,
        watched=settings.fx_drop_watched_quotes,
    )
    return current, drops
