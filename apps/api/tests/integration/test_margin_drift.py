"""``integrations.margin_drift`` — who has drifted off their target margin.

Pins the two buckets and the message, without Telegram: a SKU parked well
above its target (the refresh never lowers a price), one under it (not
rounding any more — a hand-set price or a cost that ran past), and the ones
that are not drift at all: on target, unpriced, or variable-amount.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.integrations import margin_drift

from tests.integration.test_sku_cost_margin import _seed_sku

pytestmark = pytest.mark.asyncio


async def test_find_drift_splits_above_and_below_and_ignores_the_rest(
    db_session: AsyncSession,
) -> None:
    # 13% target, priced at 13% → on target.
    await _seed_sku(db_session, "ok", cost_usdt="10.00", price_usd="11.30", margin_percent="13")
    # 13% target, selling at 25% → parked above after a supplier got cheaper.
    await _seed_sku(db_session, "high", cost_usdt="8.00", price_usd="10.00", margin_percent="13")
    # 13% target, selling at 4% → under.
    await _seed_sku(db_session, "low", cost_usdt="10.00", price_usd="10.40", margin_percent="13")
    # No target → not drift, whatever the numbers say.
    await _seed_sku(db_session, "free", cost_usdt="1.00", price_usd="9.00", margin_percent=None)
    # No cost → unpriced, not drift.
    await _seed_sku(db_session, "nocost", cost_usdt=None, price_usd="9.00", margin_percent="13")

    drift = await margin_drift.find_drift(db_session, above_pp=Decimal("5"))

    assert drift.above_total == 1
    assert drift.below_total == 1
    assert [r.sku_code for r in drift.above] == ["sk-high"]
    assert drift.above[0].actual_pct == Decimal("25.0")
    assert drift.above[0].delta_pp == Decimal("12.0")
    assert [r.sku_code for r in drift.below] == ["sk-low"]
    assert drift.below[0].actual_pct == Decimal("4.0")
    assert not drift.empty


async def test_a_small_excess_is_not_drift(db_session: AsyncSession) -> None:
    """13% target at 16% is 3 pp over — under the 5 pp bar, so nothing to say."""
    await _seed_sku(db_session, "near", cost_usdt="10.00", price_usd="11.60", margin_percent="13")

    drift = await margin_drift.find_drift(db_session, above_pp=Decimal("5"))

    assert drift.empty


async def test_format_digest_names_counts_then_rows(db_session: AsyncSession) -> None:
    await _seed_sku(db_session, "fmt", cost_usdt="8.00", price_usd="10.00", margin_percent="13")

    drift = await margin_drift.find_drift(db_session, above_pp=Decimal("5"))
    text = margin_drift.format_digest(drift, above_pp=Decimal("5"))

    assert "Выше цели" in text
    assert "1 SKU" in text
    assert "br-fmt/sk-fmt" in text
    assert "25% вместо 13%" in text
    assert "+12 пп" in text
    assert "Ниже цели" not in text
