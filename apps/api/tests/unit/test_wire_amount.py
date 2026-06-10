"""``to_wire_amount`` — lossless Decimal → JSON-number conversion.

Octo / InPay take amounts as JSON numbers. ``json.dumps`` renders a float via
``repr`` (shortest round-trip), so the wire text is exact only when
``Decimal(repr(float(amount))) == amount``. Anything else must raise instead of
silently charging a different amount (AGENTS.md §9: money is never floats —
this is the one provider-mandated boundary, guarded).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from yupay.modules.payments.gateways.base import PaymentGatewayError, to_wire_amount


def test_exact_two_decimal_amount_round_trips() -> None:
    wire = to_wire_amount(Decimal("1234567.89"))
    assert json.dumps(wire) == "1234567.89"
    assert Decimal(json.dumps(wire)) == Decimal("1234567.89")


def test_integral_amount_round_trips() -> None:
    wire = to_wire_amount(Decimal("1000.00"))
    assert Decimal(json.dumps(wire)) == Decimal("1000.00")


def test_large_uzs_amount_round_trips() -> None:
    # ~100 млрд so'm with tiyin precision — far above any real order.
    wire = to_wire_amount(Decimal("99999999999.99"))
    assert Decimal(json.dumps(wire)) == Decimal("99999999999.99")


def test_unrepresentable_amount_raises_instead_of_lying() -> None:
    with pytest.raises(PaymentGatewayError):
        to_wire_amount(Decimal("12345678901234567.89"))
