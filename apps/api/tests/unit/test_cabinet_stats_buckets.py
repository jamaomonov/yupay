"""Chart buckets for the cabinet's Statistics screen: width, and gap-free steps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.merchants.cabinet_stats import bucket_starts, granularity_for, zone

TASHKENT = ZoneInfo("Asia/Tashkent")


def test_granularity_follows_the_span() -> None:
    assert granularity_for(timedelta(hours=24)) == "hour"
    assert granularity_for(timedelta(days=7)) == "day"
    assert granularity_for(timedelta(days=30)) == "day"
    assert granularity_for(timedelta(days=200)) == "month"


def test_days_are_cut_on_the_callers_clock() -> None:
    # 20:00 UTC is already 01:00 the next day in Tashkent (UTC+5).
    start = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    end = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)
    days = bucket_starts(start, end, "day", TASHKENT)
    assert [d.date().isoformat() for d in days] == ["2026-10-02", "2026-10-03", "2026-10-04"]
    assert all(d.hour == 0 for d in days)


def test_months_roll_over_the_year() -> None:
    start = datetime(2026, 11, 15, tzinfo=UTC)
    end = datetime(2027, 2, 1, 12, tzinfo=UTC)
    months = bucket_starts(start, end, "month", TASHKENT)
    assert [(m.year, m.month) for m in months] == [(2026, 11), (2026, 12), (2027, 1), (2027, 2)]


def test_an_unknown_zone_is_refused() -> None:
    with pytest.raises(ValidationError):
        zone("Mars/Olympus")
