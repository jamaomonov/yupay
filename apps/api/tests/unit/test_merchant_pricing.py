"""Pin the merchant B2B wholesale price formula — the one home for it.

``yupay.modules.merchants.pricing`` is the only place
``cost * (1 + markup/100)``, ceiling-rounded to the cent, may be
implemented (see that module's docstring and
``docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md`` Task 5). These
tests exercise the pure functions directly against unsaved ORM instances —
no DB needed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.modules.catalog.models import Sku
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.pricing import (
    PRICE_DRIFT_TOLERANCE_PCT,
    effective_cost,
    merchant_markup_pct,
    merchant_price,
    price_to_charge,
    violates_margin_floor,
)


def _sku(*, cost_usdt: Decimal | None, b2b_markup_pct: Decimal = Decimal("7")) -> Sku:
    """An unsaved ``Sku`` carrying only the two fields pricing reads."""
    return Sku(cost_usdt=cost_usdt, b2b_markup_pct=b2b_markup_pct)


def _merchant(*, markup_adjustment_pp: Decimal | None = None) -> Merchant:
    """An unsaved ``Merchant`` carrying only the field pricing reads."""
    return Merchant(markup_adjustment_pp=markup_adjustment_pp)


@pytest.mark.parametrize(
    ("cost", "markup", "expected"),
    [
        ("8.40", "6", "8.91"),  # spec's worked example
        ("0.10", "7", "0.11"),  # ceil protects margin on cheap SKUs (0.107 -> 0.11)
        ("1.00", "0", "1.00"),  # zero markup is representable...
    ],
)
def test_price_table(cost: str, markup: str, expected: str) -> None:
    assert merchant_price(Decimal(cost), Decimal(markup)) == Decimal(expected)


def test_exact_cent_boundary_is_not_rounded_up_further() -> None:
    """A price landing exactly on a cent must not get pushed to the next one."""
    # 8.00 * 1.25 = 10.00 exactly — already a whole number of cents.
    price = merchant_price(Decimal("8.00"), Decimal("25"))
    assert price == Decimal("10.00")


def test_floor_catches_a_fat_fingered_markup() -> None:
    cost = Decimal("10")
    price = merchant_price(cost, Decimal("0.5"))  # typo for "5"
    assert violates_margin_floor(cost, price, Decimal("2")) is True


def test_none_cost_means_not_sellable() -> None:
    assert effective_cost(_sku(cost_usdt=None)) is None


def test_cost_present_is_passed_through() -> None:
    assert effective_cost(_sku(cost_usdt=Decimal("8.40"))) == Decimal("8.40")


def test_adjustment_pp_lowers_the_markup() -> None:
    sku = _sku(cost_usdt=Decimal("8.40"), b2b_markup_pct=Decimal("7"))
    merchant = _merchant(markup_adjustment_pp=Decimal("-2"))
    assert merchant_markup_pct(sku, merchant) == Decimal("5")


def test_no_adjustment_leaves_the_sku_markup_unchanged() -> None:
    sku = _sku(cost_usdt=Decimal("8.40"), b2b_markup_pct=Decimal("7"))
    merchant = _merchant(markup_adjustment_pp=None)
    assert merchant_markup_pct(sku, merchant) == Decimal("7")


def test_negative_markup_prices_below_cost() -> None:
    """A negative typo (e.g. "-7" for "7") reaches ``merchant_price`` unguarded.

    Task 4 added no DB CHECK on ``b2b_markup_pct``, so the formula is applied
    exactly as written: mathematically, that is a price below cost.
    """
    cost = Decimal("10")
    price = merchant_price(cost, Decimal("-7"))
    assert price == Decimal("9.30")
    assert price < cost


def test_floor_catches_the_negative_markup() -> None:
    """The margin floor stands between the negative-markup typo and an order.

    ``merchant_price`` itself does not refuse the price above — this is the
    guard that does.
    """
    cost = Decimal("10")
    price = merchant_price(cost, Decimal("-7"))
    assert violates_margin_floor(cost, price, Decimal("2")) is True


def test_price_exactly_at_the_floor_does_not_violate() -> None:
    cost = Decimal("10")
    floor_pct = Decimal("2")
    price = cost * (Decimal("1") + floor_pct / Decimal("100"))  # exactly at the floor
    assert violates_margin_floor(cost, price, floor_pct) is False


# ---------- the ±2% drift rule (spec §8.4) ----------


@pytest.mark.parametrize(
    ("expected", "charged"),
    [
        pytest.param("98.00", "98.00", id="exactly-2pct-below-is-inside"),
        pytest.param("102.00", "100.00", id="exactly-2pct-above-is-inside"),
        pytest.param("99.50", "99.50", id="slightly-below-charges-theirs"),
        pytest.param("100.50", "100.00", id="slightly-above-charges-ours"),
        pytest.param("100.00", "100.00", id="agreement"),
    ],
)
def test_drift_inside_the_band_charges_the_lower_of_the_two(expected: str, charged: str) -> None:
    assert price_to_charge(Decimal("100.00"), Decimal(expected)) == Decimal(charged)


@pytest.mark.parametrize(
    "expected",
    ["97.99", "102.01", "0.01", "1000.00"],
    ids=["just-below", "just-above", "far-below", "far-above"],
)
def test_drift_outside_the_band_is_refused(expected: str) -> None:
    """``None`` is the caller's cue to raise ``422 price_changed``."""
    assert price_to_charge(Decimal("100.00"), Decimal(expected)) is None


def test_the_band_is_a_percentage_of_our_price_not_a_flat_amount() -> None:
    """A cheap SKU's band is cents; an expensive one's is dollars."""
    assert price_to_charge(Decimal("1.00"), Decimal("0.98")) == Decimal("0.98")
    assert price_to_charge(Decimal("1.00"), Decimal("0.97")) is None
    assert price_to_charge(Decimal("500.00"), Decimal("490.00")) == Decimal("490.00")
    assert price_to_charge(Decimal("500.00"), Decimal("489.99")) is None


def test_the_documented_gaming_vector_is_real_and_bounded() -> None:
    """The rule as specified lets a merchant take the full tolerance, always.

    Pinned rather than fixed: the spec is the owner's decision and this is
    what it says. The point of the test is that the discount is exactly the
    tolerance and nothing more — so if someone widens
    ``PRICE_DRIFT_TOLERANCE_PCT`` believing it only affects error handling,
    this says out loud what else moves with it.
    """
    ours = Decimal("107.00")
    always_shaved = ours * (Decimal("1") - PRICE_DRIFT_TOLERANCE_PCT / Decimal("100"))
    assert price_to_charge(ours, always_shaved) == always_shaved
