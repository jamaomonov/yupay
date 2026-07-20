"""The gate a rate must pass before it may price an order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from yupay.core.config import get_settings
from yupay.modules.pricing.fx_guard import RateRejected, check_rate

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
GOOD = Decimal("13000")


def _check(rate: Decimal, *, age: timedelta = timedelta(0), previous: Decimal | None = GOOD):
    check_rate(
        rate,
        fetched_at=NOW - age,
        previous=previous,
        now_=NOW,
        settings=get_settings(),
    )


def test_accepts_a_fresh_plausible_rate() -> None:
    _check(Decimal("13100"))  # no exception


def test_rejects_a_non_positive_rate() -> None:
    with pytest.raises(RateRejected) as exc:
        _check(Decimal("0"))
    assert exc.value.reason == "non_positive"


def test_rejects_a_stale_rate() -> None:
    with pytest.raises(RateRejected) as exc:
        _check(GOOD, age=timedelta(hours=7))
    assert exc.value.reason == "stale"


def test_rejects_a_rate_that_halved() -> None:
    # The failure that motivated the gate: a provider returns a number that
    # looks like a rate but is half the real one.
    with pytest.raises(RateRejected) as exc:
        _check(GOOD / 2)
    assert exc.value.reason == "deviation"


def test_rejects_a_rate_outside_the_absolute_band() -> None:
    with pytest.raises(RateRejected) as exc:
        _check(Decimal("1000"), previous=None)
    assert exc.value.reason == "out_of_band"


def test_accepts_a_first_ever_rate_inside_the_band() -> None:
    # No previous value to compare against — the band is the only guard.
    _check(Decimal("13000"), previous=None)


def test_allows_movement_within_the_threshold() -> None:
    _check(GOOD * Decimal("1.10"))


# --- Boundary pins -----------------------------------------------------
#
# These pin the current, deliberate behaviour at each threshold edge so the
# money-path comparisons (`>` vs `>=`, `<=` vs `<`) can't drift silently.
# Every check below is inclusive of the configured limit: exactly-at-the-limit
# is ACCEPTED, only strictly-past-the-limit is REJECTED.


def test_accepts_a_rate_exactly_at_the_max_age() -> None:
    settings = get_settings()
    _check(GOOD, age=timedelta(seconds=settings.pricing_fx_max_age_seconds))


def test_accepts_a_deviation_exactly_at_the_max_percentage() -> None:
    settings = get_settings()
    previous = GOOD
    factor = Decimal("1") + settings.pricing_fx_max_deviation_pct / Decimal("100")
    _check(previous * factor, previous=previous)


def test_accepts_a_rate_exactly_at_the_band_floor() -> None:
    settings = get_settings()
    _check(settings.pricing_fx_min_rate_uzs, previous=None)


def test_accepts_a_rate_exactly_at_the_band_ceiling() -> None:
    settings = get_settings()
    _check(settings.pricing_fx_max_rate_uzs, previous=None)
