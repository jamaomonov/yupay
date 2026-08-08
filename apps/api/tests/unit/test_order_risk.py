"""The manual-review rule (ADR-0047)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from yupay.core.config import Settings, get_settings
from yupay.modules.orders.risk import REASON_LARGE_AMOUNT, review_reason


def _settings(threshold: str) -> Settings:
    base = get_settings().model_dump()
    base["manual_review_threshold_usd"] = Decimal(threshold)
    return Settings(**base)


def _order(total_usd: str) -> Any:
    return cast("Any", SimpleNamespace(total_usd=Decimal(total_usd)))


def test_an_ordinary_order_is_fulfilled_automatically() -> None:
    # The median production order is about $1. Holding those would replace an
    # automatic service with a manual one and lose the product.
    assert review_reason(_order("1.15"), settings=_settings("40")) is None
    assert review_reason(_order("11.00"), settings=_settings("40")) is None


def test_a_large_order_is_held() -> None:
    # $202 is the real order this rule was written after: paid, failed two
    # seconds later, and it was also the largest the platform had ever taken.
    assert review_reason(_order("202.00"), settings=_settings("40")) == REASON_LARGE_AMOUNT


def test_the_threshold_itself_is_held_not_let_through() -> None:
    """``>=``, not ``>``. An operator setting the limit to 40 means "40 is big
    enough to look at", and off-by-one on a money control is not a detail."""
    assert review_reason(_order("40.00"), settings=_settings("40")) == REASON_LARGE_AMOUNT
    assert review_reason(_order("39.99"), settings=_settings("40")) is None


def test_zero_disables_the_rule() -> None:
    # An escape hatch that does not need a code change: if the hold ever gets in
    # the way at 3am, it can be turned off from the environment.
    assert review_reason(_order("10000"), settings=_settings("0")) is None
