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


# ---------- the ±2% drift rule (spec §8.4, amended by the owner 2026-09-07) ----------


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param("98.00", id="exactly-2pct-below-is-inside"),
        pytest.param("102.00", id="exactly-2pct-above-is-inside"),
        pytest.param("99.50", id="slightly-below"),
        pytest.param("100.50", id="slightly-above"),
        pytest.param("100.00", id="agreement"),
    ],
)
def test_drift_inside_the_band_always_charges_our_price(expected: str) -> None:
    """The band accepts or rejects; it never sets the price.

    Whichever side of ours the merchant's number falls, an accepted order
    costs ``current``. Charging the lower of the two — what the rule did
    until 2026-09-07 — is the regression this parametrisation catches.
    """
    assert price_to_charge(Decimal("100.00"), Decimal(expected)) == Decimal("100.00")


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
    assert price_to_charge(Decimal("1.00"), Decimal("0.98")) == Decimal("1.00")
    assert price_to_charge(Decimal("1.00"), Decimal("0.97")) is None
    assert price_to_charge(Decimal("500.00"), Decimal("490.00")) == Decimal("500.00")
    assert price_to_charge(Decimal("500.00"), Decimal("489.99")) is None


def test_quoting_low_buys_at_our_price_and_takes_no_discount() -> None:
    """The old rule's standing 2% giveaway, pinned closed.

    ``/catalog`` is live-computed and never cached, so a merchant can read
    our exact price and send ``current × (1 - tolerance)`` on every order.
    Under ``min(current, expected)`` that was a guaranteed 2% off wholesale —
    ~31% of the margin at the default 7% markup, and unbounded by
    :func:`violates_margin_floor`, which runs on our price before this rule
    and never re-checks what was charged. Owner decision 2026-09-07: the
    quote is a tolerance, not a bid. If this test starts failing, an order
    is being charged the merchant's number again.
    """
    ours = Decimal("107.00")
    shaved = ours * (Decimal("1") - PRICE_DRIFT_TOLERANCE_PCT / Decimal("100"))
    charged = price_to_charge(ours, shaved)
    assert charged is not None
    assert charged == ours
    assert charged > shaved


def test_a_floor_level_markup_can_no_longer_be_quoted_below_cost() -> None:
    """The concrete loss the old rule allowed: a sale under our own cost.

    Cost 100.00 at a 2% markup prices at 102.00 and clears a 2% margin floor
    exactly; a merchant sending 99.96 drifts by exactly the tolerance, so the
    band accepts. The lower-of-the-two rule charged 99.96 — below cost, with
    the floor already satisfied and never re-evaluated.
    """
    cost = Decimal("100.00")
    ours = merchant_price(cost, Decimal("2"))
    assert ours == Decimal("102.00")
    assert violates_margin_floor(cost, ours, Decimal("2")) is False
    below_cost = Decimal("99.96")
    charged = price_to_charge(ours, below_cost)
    assert charged is not None
    assert charged == ours
    assert charged > cost


def test_a_non_positive_price_is_refused_rather_than_divided_by() -> None:
    """``current`` is the drift denominator; a zero must not reach it."""
    assert price_to_charge(Decimal("0"), Decimal("1.00")) is None
    assert price_to_charge(Decimal("-1.00"), Decimal("1.00")) is None
