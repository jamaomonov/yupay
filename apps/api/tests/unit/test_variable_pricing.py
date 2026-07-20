from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.pricing.variable import (
    display_rate,
    price_in_quote,
    to_units,
    validate_amount,
)


def test_whole_dollars_convert_exactly() -> None:
    assert to_units(Decimal("5"), fee_rate=Decimal("0")) == 5000


def test_cents_convert_exactly() -> None:
    # 1000 units = $1, so a cent is 10 units and two decimals are exact.
    assert to_units(Decimal("10.50"), fee_rate=Decimal("0")) == 10500


def test_fee_is_grossed_up_so_the_customer_still_receives_the_amount() -> None:
    # 5% fee: send enough that ~$10 survives it.
    assert to_units(Decimal("10"), fee_rate=Decimal("0.05")) == 10527


def test_gross_up_rounds_up_never_short_changing_the_customer() -> None:
    units = to_units(Decimal("9.99"), fee_rate=Decimal("0.03"))
    assert units * (Decimal("1") - Decimal("0.03")) >= Decimal("9.99") * 1000


def test_display_rate_applies_the_margin() -> None:
    assert display_rate(Decimal("13000"), Decimal("1.08")) == Decimal("14040")


def test_price_is_amount_times_display_rate() -> None:
    assert price_in_quote(Decimal("10"), rate=Decimal("14025")) == Decimal("140250")


def test_amount_below_minimum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_amount(Decimal("0.50"), minimum=Decimal("1"), maximum=Decimal("300"))


def test_amount_above_maximum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_amount(Decimal("301"), minimum=Decimal("1"), maximum=Decimal("300"))


def test_more_than_two_decimals_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_amount(Decimal("10.123"), minimum=Decimal("1"), maximum=Decimal("300"))


def test_negative_amount_is_rejected_in_to_units() -> None:
    with pytest.raises(ValidationError):
        to_units(Decimal("-5"), fee_rate=Decimal("0.05"))


def test_zero_amount_is_rejected_in_to_units() -> None:
    with pytest.raises(ValidationError):
        to_units(Decimal("0"), fee_rate=Decimal("0.05"))


def test_amount_at_exact_minimum_is_accepted() -> None:
    # Should not raise; amount == minimum is valid.
    validate_amount(Decimal("1"), minimum=Decimal("1"), maximum=Decimal("300"))


def test_amount_at_exact_maximum_is_accepted() -> None:
    # Should not raise; amount == maximum is valid.
    validate_amount(Decimal("300"), minimum=Decimal("1"), maximum=Decimal("300"))
