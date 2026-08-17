"""A variable amount typed in something other than dollars.

The Steam wallet is bought in dollars, so the number the customer types is the
number that gets billed. Telegram Stars is bought in stars at $0.01545 each, and
the two must not drift: the supplier is sent an integer star count, so a
customer who asked for 500 has to be charged for exactly 500.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.modules.catalog.models import Sku
from yupay.modules.orders.service import _snap_to_unit

STARS_PER_USD = Decimal("64.705882")


def _sku(*, variable: bool = True, per_usd: Decimal | None = STARS_PER_USD) -> Sku:
    return Sku(
        id="sku-stars",
        product_id="p1",
        sku_code="tg-stars-any",
        price_usd=Decimal("1"),
        variable_amount=variable,
        units_per_usd=per_usd,
        amount_unit="stars" if per_usd is not None else None,
    )


@pytest.mark.parametrize("stars", [50, 75, 137, 500, 1000, 2500, 50_000])
def test_a_star_count_survives_the_round_trip_through_dollars(stars: int) -> None:
    """The storefront divides, we multiply back. If that did not land on the
    same integer, the customer would be credited a different amount than the
    one they paid for."""
    as_usd = (Decimal(stars) / STARS_PER_USD).quantize(Decimal("0.000001"))

    snapped = _snap_to_unit(as_usd, _sku())

    assert (snapped * STARS_PER_USD).quantize(Decimal("1")) == stars


def test_float_noise_from_the_browser_is_snapped_back() -> None:
    # What a JS `500 / 64.705882` can arrive as after rounding for the wire.
    noisy = Decimal("7.727270")

    snapped = _snap_to_unit(noisy, _sku())

    assert (snapped * STARS_PER_USD).quantize(Decimal("1")) == 500
    assert snapped != noisy


def test_a_dollar_priced_sku_is_left_exactly_as_it_was() -> None:
    """Every SKU that exists today. Rounding a Steam top-up to a whole
    "unit" would quietly change what the customer asked to pay."""
    steam = _sku(per_usd=None)

    assert _snap_to_unit(Decimal("10.55"), steam) == Decimal("10.55")


def test_a_fixed_price_sku_is_never_snapped() -> None:
    assert _snap_to_unit(Decimal("3.33"), _sku(variable=False)) == Decimal("3.33")


def test_an_amount_below_half_a_unit_is_left_for_the_bounds_check() -> None:
    """Snapping it to zero would price a sale at nothing; the minimum is what
    should reject it, with a message that says so."""
    tiny = Decimal("0.000001")

    assert _snap_to_unit(tiny, _sku()) == tiny
