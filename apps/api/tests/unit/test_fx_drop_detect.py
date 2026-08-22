"""Drop-only FX tripwire: 6% down trips, up and first-tick do not."""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.fx.drop_detect import detect_drops

WATCHED = ("UZS", "RUB")
THRESHOLD = Decimal("6")


def test_drop_just_over_threshold_trips() -> None:
    drops = detect_drops(
        {"UZS": Decimal("12700")},
        {"UZS": Decimal("11900")},
        threshold_pct=THRESHOLD,
        watched=WATCHED,
    )
    assert len(drops) == 1
    assert drops[0].quote == "UZS"
    assert drops[0].drop_pct > THRESHOLD


def test_drop_exactly_at_threshold_does_not_trip() -> None:
    prev = Decimal("100")
    drops = detect_drops(
        {"UZS": prev},
        {"UZS": prev * Decimal("0.94")},
        threshold_pct=THRESHOLD,
        watched=WATCHED,
    )
    assert drops == []


def test_rise_is_ignored() -> None:
    drops = detect_drops(
        {"UZS": Decimal("12000")},
        {"UZS": Decimal("14000")},
        threshold_pct=THRESHOLD,
        watched=WATCHED,
    )
    assert drops == []


def test_first_tick_without_history_does_not_trip() -> None:
    drops = detect_drops(
        {},
        {"UZS": Decimal("10000")},
        threshold_pct=THRESHOLD,
        watched=WATCHED,
    )
    assert drops == []


def test_usdt_is_not_watched() -> None:
    drops = detect_drops(
        {"USDT": Decimal("1.00"), "UZS": Decimal("12700")},
        {"USDT": Decimal("0.80"), "UZS": Decimal("12700")},
        threshold_pct=THRESHOLD,
        watched=WATCHED,
    )
    assert drops == []


def test_rub_drop_trips_independently() -> None:
    drops = detect_drops(
        {"RUB": Decimal("90"), "UZS": Decimal("12700")},
        {"RUB": Decimal("80"), "UZS": Decimal("12700")},
        threshold_pct=THRESHOLD,
        watched=WATCHED,
    )
    assert [d.quote for d in drops] == ["RUB"]
