"""Unit tests for analytics schema range parsing."""

from __future__ import annotations

import pytest
from yupay.modules.stats.schemas import AnalyticsRange, range_to_days


def test_range_values() -> None:
    assert {r.value for r in AnalyticsRange} == {"7d", "30d", "90d"}


@pytest.mark.parametrize(("r", "days"), [("7d", 7), ("30d", 30), ("90d", 90)])
def test_range_to_days(r: str, days: int) -> None:
    assert range_to_days(AnalyticsRange(r)) == days
