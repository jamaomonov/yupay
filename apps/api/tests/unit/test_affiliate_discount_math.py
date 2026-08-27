"""The discount arithmetic. Pure functions — no database, no container.

The property that matters is that the parts sum to the whole: a dropped
rounding remainder is money that silently reappears as margin, on exactly the
orders where margin is thinnest.
"""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.affiliate.discount import discount_amount, distribute_discount_usd


def test_discount_is_rounded_to_a_payable_amount() -> None:
    """UZS has no subunit in practice — Payme and Click both reject fractions."""
    assert discount_amount(Decimal("12414"), Decimal("7"), "UZS") == Decimal("869")
    assert discount_amount(Decimal("20.00"), Decimal("10"), "USD") == Decimal("2.00")


def test_distribution_splits_proportionally_and_loses_nothing() -> None:
    shares = distribute_discount_usd([Decimal("10"), Decimal("20"), Decimal("30")], Decimal("6"))
    assert sum(shares) == Decimal("6")
    assert shares[2] > shares[0]


def test_distribution_of_awkward_thirds_still_sums_exactly() -> None:
    """Three equal lines and a discount that does not divide evenly."""
    shares = distribute_discount_usd(
        [Decimal("1"), Decimal("1"), Decimal("1")], Decimal("0.0000010")
    )
    assert sum(shares) == Decimal("0.0000010")


def test_distribution_handles_one_line_and_no_lines() -> None:
    assert distribute_discount_usd([Decimal("10")], Decimal("1")) == [Decimal("1")]
    assert distribute_discount_usd([], Decimal("1")) == []
    assert distribute_discount_usd([Decimal("0")], Decimal("1")) == [Decimal("0")]
