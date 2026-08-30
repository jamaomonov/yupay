"""The manual-review rule (ADR-0047)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from yupay.core.config import Settings, get_settings
from yupay.modules.orders.risk import (
    REASON_GEO_MISMATCH,
    REASON_LARGE_AMOUNT,
    REASON_ROLLING_SUM,
    REASON_SHARED_IDENTITY,
    REASON_VELOCITY,
    WindowOrder,
    _amount_reason,
    _csv,
    _effective_threshold,
    _geo_reason,
    _window_reason,
)


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


# ---------- window rules (rolling sum + velocity) ----------


def _cfg(
    sum24: str = "25",
    sum7d: str = "60",
    velocity: int = 5,
    buyers: int = 3,
    liquid: str = "roblox,telegram-stars,steam",
    home: str = "Asia/Tashkent,Asia/Samarkand",
) -> Settings:
    base = get_settings().model_dump()
    base.update(
        risk_sum_24h_usd=Decimal(sum24),
        risk_sum_7d_usd=Decimal(sum7d),
        risk_velocity_24h=velocity,
        risk_distinct_buyers_7d=buyers,
        risk_liquid_brands=liquid,
        risk_home_timezones=home,
        risk_jitter=False,
    )
    return Settings(**base)


_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _wo(
    minutes_ago: int,
    usd: str,
    *,
    buyer: str | None = "me@x.com",
    ip: str | None = None,
    device: str | None = None,
    targets: set[str] | None = None,
) -> WindowOrder:
    return WindowOrder(
        id=f"o-{minutes_ago}-{usd}",
        paid_at=_NOW - timedelta(minutes=minutes_ago),
        total_usd=Decimal(usd),
        buyer=buyer,
        ip=ip,
        device=device,
        targets=frozenset(targets or ()),
    )


def test_rolling_sum_24h_holds_the_order_that_crosses_the_cap() -> None:
    # Ten $18 Roblox orders was the real attack; three $11 is the same move
    # under the lowered threshold. Sum includes the current order.
    recent = [_wo(60, "11"), _wo(120, "11")]  # same buyer
    assert _window_reason(_wo(0, "11"), recent, _cfg()) == REASON_ROLLING_SUM


def test_sum_counts_any_shared_key_not_only_buyer() -> None:
    recent = [
        _wo(60, "11", buyer="a@x.com", ip="203.0.113.7"),
        _wo(120, "11", buyer="b@x.com", ip="203.0.113.7"),
    ]
    current = _wo(0, "11", buyer="c@x.com", ip="203.0.113.7")
    assert _window_reason(current, recent, _cfg()) == REASON_ROLLING_SUM


def test_a_neighbour_sharing_nothing_is_invisible() -> None:
    recent = [_wo(60, "1000", buyer="stranger@x.com", ip="198.51.100.1", device="ffff")]
    assert (
        _window_reason(
            _wo(0, "2", buyer="me@x.com", ip="203.0.113.7", device="aaaa"), recent, _cfg()
        )
        is None
    )


def test_velocity_holds_the_sixth_order_in_a_day() -> None:
    recent = [_wo(i * 10, "1") for i in range(1, 6)]  # five paid, same buyer
    assert _window_reason(_wo(0, "1"), recent, _cfg()) == REASON_VELOCITY


def test_the_7d_cap_catches_a_slow_drip() -> None:
    recent = [_wo(60 * 24 * d, "9") for d in range(1, 7)]  # $9/day for 6 days = $54
    assert _window_reason(_wo(0, "9"), recent, _cfg()) == REASON_ROLLING_SUM  # 63 >= 60


def test_zeroes_disable_each_window_rule() -> None:
    cfg = _cfg(sum24="0", sum7d="0", velocity=0)
    recent = [_wo(10, "500") for _ in range(20)]
    assert _window_reason(_wo(0, "500"), recent, cfg) is None


def test_target_account_links_orders_with_nothing_else_shared() -> None:
    # The 7-orders-to-one-Stars-username pattern: buyers, IPs, devices all
    # differ; the destination does not.
    recent = [
        _wo(60, "11", buyer="a@x.com", ip="203.0.113.1", device="aa", targets={"durov"}),
        _wo(90, "11", buyer="b@x.com", ip="203.0.113.2", device="bb", targets={"durov"}),
    ]
    current = _wo(0, "11", buyer="c@x.com", ip="203.0.113.3", device="cc", targets={"durov"})
    assert _window_reason(current, recent, _cfg()) == REASON_ROLLING_SUM


# ---------- _csv ----------


def test_csv_lowercases_trims_and_drops_empties() -> None:
    assert _csv(" Roblox, telegram-stars ,,STEAM") == frozenset(
        {"roblox", "telegram-stars", "steam"}
    )
    assert _csv("") == frozenset()


# ---------- shared identity (rule 4) ----------


def test_one_device_serving_three_buyers_is_held() -> None:
    recent = [
        _wo(60, "1", buyer="a@x.com", device="dd"),
        _wo(90, "1", buyer="b@x.com", device="dd"),
    ]
    assert (
        _window_reason(_wo(0, "1", buyer="c@x.com", device="dd"), recent, _cfg())
        == REASON_SHARED_IDENTITY
    )


def test_one_buyer_on_two_devices_is_not_shared_identity() -> None:
    # A person with a phone and a laptop is not a fraud ring.
    recent = [
        _wo(60, "1", buyer="a@x.com", device="d1"),
        _wo(90, "1", buyer="a@x.com", device="d2"),
    ]
    assert _window_reason(_wo(0, "1", buyer="a@x.com", device="d3"), recent, _cfg()) is None


# ---------- geo mismatch (rule 5) ----------


def test_guest_liquid_brand_foreign_tz_is_held() -> None:
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg()) == REASON_GEO_MISMATCH


def test_signed_in_or_home_tz_or_illiquid_brand_passes() -> None:
    cfg = _cfg()
    assert _geo_reason(False, frozenset({"roblox"}), "Europe/Kiev", cfg) is None
    assert _geo_reason(True, frozenset({"roblox"}), "Asia/Tashkent", cfg) is None
    assert _geo_reason(True, frozenset({"free-fire"}), "Europe/Kiev", cfg) is None
    assert _geo_reason(True, frozenset({"roblox"}), None, cfg) is None  # no tz = no claim
    assert (
        _geo_reason(True, frozenset({"free-fire", "roblox"}), "Europe/Kiev", cfg)
        == REASON_GEO_MISMATCH
    )  # any liquid item


def test_empty_lists_disable_the_geo_rule() -> None:
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg(liquid="", home="")) is None
