"""Trust gate for rates that set customer-facing prices.

The FX layer already fails over between providers, caches, and rejects
non-positive numbers. What it cannot see is a rate that *parses* fine but is
wrong — half the real value, or yesterday's. Applying our margin multiplier to
such a number and continuing to sell is how a pricing bug becomes a refund
queue, so pricing runs rates through here first and refuses to sell when a
rate cannot be trusted.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.logging import get_logger
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.models import FxRate
from yupay.modules.fx.service import FxUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.pricing.fx_guard")

RejectReason = Literal["unavailable", "stale", "deviation", "out_of_band", "non_positive"]


# Named for the domain verb, not suffixed "...Error": this is the fixed
# cross-module contract that pricing/checkout call sites (Task 4/5) catch by
# name (`except RateRejected`), matching the interface this task was specced
# against.
class RateRejected(Exception):  # noqa: N818
    """The rate must not be used to price anything."""

    def __init__(self, reason: RejectReason, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason: RejectReason = reason


def check_rate(
    rate: Decimal,
    *,
    fetched_at: datetime,
    previous: Decimal | None,
    now_: datetime,
    settings: Settings,
) -> None:
    """Raise :class:`RateRejected` unless ``rate`` may set a price.

    Checks run in this order:

    1. ``non_positive`` — a zero or negative rate is a data error, not a
       pricing signal. Must run before the band check, or a zero rate would
       be (correctly, but less clearly) reported as ``out_of_band`` instead.
    2. ``stale`` — the rate is older than we're willing to trust.
    3. ``deviation`` — when we have a previous known-good rate, a rate that
       jumped too far from it is the most specific and actionable signal
       (e.g. a provider silently halving its output), so it's reported ahead
       of the coarser absolute-band check. Skipped when there is no
       previous rate to compare against.
    4. ``out_of_band`` — absolute sanity floor/ceiling. This is the only
       guard left for a first-ever rate with no history, and also catches
       any implausible rate that happens to have a small (or no) deviation
       from a previous rate that was itself already off.
    """
    if rate <= 0:
        raise RateRejected("non_positive", f"rate={rate}")

    age = (now_ - fetched_at).total_seconds()
    if age > settings.pricing_fx_max_age_seconds:
        raise RateRejected("stale", f"age={age:.0f}s")

    if previous is not None and previous > 0:
        deviation = abs(rate - previous) / previous * Decimal("100")
        if deviation > settings.pricing_fx_max_deviation_pct:
            raise RateRejected("deviation", f"{deviation:.1f}% from {previous}")

    if not (settings.pricing_fx_min_rate_uzs <= rate <= settings.pricing_fx_max_rate_uzs):
        raise RateRejected("out_of_band", f"rate={rate}")


async def _previous_rate(db: AsyncSession, *, quote: str, exclude_id: str) -> Decimal | None:
    """Most recent ``fx_rates`` row for USD→``quote`` other than ``exclude_id``."""
    stmt = (
        select(FxRate.rate)
        .where(FxRate.base == "USD", FxRate.quote == quote, FxRate.id != exclude_id)
        .order_by(FxRate.fetched_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def guarded_usd_rate(db: AsyncSession, *, quote: str) -> Decimal:
    """USD→``quote`` rate that has passed the gate, or :class:`RateRejected`."""
    settings = get_settings()
    fx = build_default_service()
    try:
        snap = await fx.snapshot(db, base="USD", quote=quote)
    except FxUnavailableError as exc:
        raise RateRejected("unavailable", str(exc)) from exc

    previous = await _previous_rate(db, quote=quote, exclude_id=snap.id)
    try:
        check_rate(
            snap.rate,
            fetched_at=snap.fetched_at,
            previous=previous,
            now_=now(),
            settings=settings,
        )
    except RateRejected as exc:
        # Loud on purpose: this is money, and the product disappears from sale
        # until someone looks.
        log.exception("pricing.rate_rejected", reason=exc.reason, quote=quote, detail=str(exc))
        raise
    return snap.rate


__all__ = ["RateRejected", "RejectReason", "check_rate", "guarded_usd_rate"]
