"""The manual-review rule (ADR-0047)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from yupay.core.config import Settings, get_settings
from yupay.modules.orders.risk import REASON_LARGE_AMOUNT, _amount_reason, _effective_threshold


def _settings(threshold: str, *, jitter: bool = True) -> Settings:
    base = get_settings().model_dump()
    base["manual_review_threshold_usd"] = Decimal(threshold)
    base["risk_jitter"] = jitter
    return Settings(**base)


def _order(total_usd: str, *, order_id: str = "0192aaaa-bbbb-cccc-dddd-eeeeffff0000") -> Any:
    return cast("Any", SimpleNamespace(id=order_id, total_usd=Decimal(total_usd)))


def test_an_ordinary_order_is_fulfilled_automatically() -> None:
    # The median production order is about $1. Holding those would replace an
    # automatic service with a manual one and lose the product.
    assert _amount_reason(_order("1.15"), _settings("40", jitter=False)) is None
    assert _amount_reason(_order("11.00"), _settings("40", jitter=False)) is None


def test_a_large_order_is_held() -> None:
    # $202 is the real order this rule was written after: paid, failed two
    # seconds later, and it was also the largest the platform had ever taken.
    assert _amount_reason(_order("202.00"), _settings("40", jitter=False)) == REASON_LARGE_AMOUNT


def test_the_threshold_itself_is_held_not_let_through() -> None:
    """``>=``, not ``>``. An operator setting the limit to 40 means "40 is big
    enough to look at", and off-by-one on a money control is not a detail."""
    assert _amount_reason(_order("40.00"), _settings("40", jitter=False)) == REASON_LARGE_AMOUNT
    assert _amount_reason(_order("39.99"), _settings("40", jitter=False)) is None


def test_zero_disables_the_rule() -> None:
    # An escape hatch that does not need a code change: if the hold ever gets in
    # the way at 3am, it can be turned off from the environment.
    assert _amount_reason(_order("10000"), _settings("0", jitter=False)) is None


def test_jitter_stays_inside_its_band_and_is_stable() -> None:
    cfg = _settings("40")  # risk_jitter left True here
    t1 = _effective_threshold("0192aaaa-bbbb-cccc-dddd-eeeeffff0001", cfg)
    assert t1 == _effective_threshold("0192aaaa-bbbb-cccc-dddd-eeeeffff0001", cfg)
    assert Decimal("24") <= t1 < Decimal("40")  # [0.6, 1.0) x base


def test_jitter_off_means_the_flat_threshold() -> None:
    cfg = _settings("40", jitter=False)
    assert _effective_threshold("any-id", cfg) == Decimal("40")
