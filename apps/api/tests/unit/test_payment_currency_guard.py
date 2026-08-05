"""Currency-confusion guard for the UZ acquirer inbound handlers.

Click/Payme/Uzum settle only in UZS. Their inbound state/amount checks matched
the numeric amount against ``order.total_charged`` but did not assert the order
is actually priced in UZS — so a non-UZS order (e.g. a RUB order whose
``total_charged`` is 5000 RUB) could be settled by paying 5000 *soums*, whose
tiyin amount matches numerically. These tests pin the guard: a non-UZS order
must be rejected by each handler even when the amount matches.
"""

from decimal import Decimal

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order before pulling in service internals

from yupay.modules.click.errors import ClickError
from yupay.modules.click.service import _check_order_state as click_check_state
from yupay.modules.orders.models import Order
from yupay.modules.payme.errors import PaymeError
from yupay.modules.payme.service import _check_perform, _expected_tiyin
from yupay.modules.uzum.errors import UzumError
from yupay.modules.uzum.service import _check_order_state as uzum_check_state


def _order(currency: str) -> Order:
    """A payable order with the given quote currency (in-memory, no DB)."""
    return Order(status="pending_payment", currency=currency, total_charged=Decimal("5000"))


def test_payme_rejects_non_uzs_order_even_when_amount_matches() -> None:
    order = _order("RUB")
    # The exploit: the tiyin amount equals total_charged*100, so the amount
    # check alone passes — the currency guard must still reject it.
    with pytest.raises(PaymeError):
        _check_perform(order, _expected_tiyin(order))


def test_click_rejects_non_uzs_order() -> None:
    with pytest.raises(ClickError):
        click_check_state(_order("RUB"))


def test_uzum_rejects_non_uzs_order() -> None:
    with pytest.raises(UzumError):
        uzum_check_state(_order("RUB"))


def test_uzs_orders_still_pass_the_guard() -> None:
    # A genuine UZS order at pending_payment must NOT be rejected by the guard.
    uzs = _order("UZS")
    _check_perform(uzs, _expected_tiyin(uzs))  # payme: no raise
    click_check_state(uzs)  # no raise
    uzum_check_state(uzs)  # no raise
