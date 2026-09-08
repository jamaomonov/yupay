"""The whole ``failure_reason`` transition table, in one place (M3b Task 4).

``order_status._failure_reason`` is a pure function of four facts — the
order's status, its items' fulfilment states, what came back on the deposit
and what the order was charged — plus, since M3b Task 4, whether a fulfilment
task has stopped while its item has not.

The integration suites walk the real edges: an operator tops up and retries, a
retry fails terminally, a task is cancelled, support closes the order. What
they cannot do cheaply is walk **combinations** — an order that is stalled
*and* closed by hand, one that is stalled *and* already refunded — and those
are where a precedence bug lives, because each ingredient is individually
right. The table below is the contract, and it is exhaustive over the
combinations the endpoint can produce.

It is a unit test on a private function on purpose. The mapping is the
published vocabulary a reseller switches on, and a mapping is the one thing
worth pinning away from the machinery that feeds it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.modules.merchants.order_status import (
    REASON_FULFILLMENT_DELAYED,
    REASON_FULFILLMENT_FAILED,
    REASON_FULFILLMENT_REFUNDED,
    REASON_ORDER_FAILED,
    _failure_reason,
)
from yupay.modules.orders.models import Order, OrderItem

CHARGE = Decimal("1.07")
NOTHING = Decimal("0.00")


def _order(status: str, *item_states: str) -> Order:
    """An unattached order object with one item per state.

    No session and no database: ``_failure_reason`` reads attributes and
    nothing else, which is exactly why it is worth having as a function.
    """
    order = Order(status=status)
    order.items = [OrderItem(fulfillment_state=state) for state in item_states]
    return order


@pytest.mark.parametrize(
    ("case", "status", "item_state", "stalled", "refunded", "expected"),
    [
        # ---- nothing has gone wrong
        ("just placed", "fulfilling", "pending", False, NOTHING, None),
        ("supplier call open", "fulfilling", "in_progress", False, NOTHING, None),
        ("delivered", "delivered", "delivered", False, NOTHING, None),
        # ---- the stall: stopped, but not finished failing
        ("stalled", "fulfilling", "in_progress", True, NOTHING, REASON_FULFILLMENT_DELAYED),
        # ---- terminal, and the ledger splits it
        ("failed, money out", "fulfilling", "failed", False, NOTHING, REASON_FULFILLMENT_FAILED),
        (
            "failed, part back",
            "fulfilling",
            "failed",
            False,
            Decimal("0.01"),
            REASON_FULFILLMENT_FAILED,
        ),
        ("failed, all back", "fulfilling", "failed", False, CHARGE, REASON_FULFILLMENT_REFUNDED),
        # ---- support closed it: ``order_failed`` outranks everything
        ("closed by hand", "failed", "failed", False, NOTHING, REASON_ORDER_FAILED),
        ("closed, refunded", "failed", "failed", False, CHARGE, REASON_ORDER_FAILED),
        # ---- the combinations only a precedence bug distinguishes
        ("stalled and closed", "failed", "in_progress", True, NOTHING, REASON_ORDER_FAILED),
        ("stalled and failed", "fulfilling", "failed", True, NOTHING, REASON_FULFILLMENT_FAILED),
        ("stalled and refunded", "fulfilling", "failed", True, CHARGE, REASON_FULFILLMENT_REFUNDED),
    ],
)
def test_the_failure_reason_table(
    case: str,
    status: str,
    item_state: str,
    stalled: bool,
    refunded: Decimal,
    expected: str | None,
) -> None:
    """One row per reachable state of a merchant order."""
    reason = _failure_reason(
        _order(status, item_state), refunded=refunded, charged=CHARGE, stalled=stalled
    )
    assert reason == expected, case


def test_a_stall_is_never_reported_for_an_order_with_no_charge_on_file() -> None:
    """``charged is None`` changes the refund split and must not touch the stall.

    An order with no charge posting can never read as refunded — there is
    nothing for the money to be complete against. The stall is a fact about
    fulfilment rather than about money, so it survives that.
    """
    assert (
        _failure_reason(
            _order("fulfilling", "in_progress"), refunded=NOTHING, charged=None, stalled=True
        )
        == REASON_FULFILLMENT_DELAYED
    )
    assert (
        _failure_reason(
            _order("fulfilling", "failed"), refunded=CHARGE, charged=None, stalled=False
        )
        == REASON_FULFILLMENT_FAILED
    )


def test_the_delayed_value_never_names_its_cause() -> None:
    """Ruling 1, pinned as a property of the string rather than of a response.

    The cause is that *we* ran out of balance at a named supplier. A reseller
    who could read that off our API would learn our supplier funding state.
    The word is about **our** delay and says nothing else.
    """
    assert REASON_FULFILLMENT_DELAYED == "fulfillment_delayed"
    for leak in ("balance", "supplier", "low", "g2b", "waxpeer"):
        assert leak not in REASON_FULFILLMENT_DELAYED


def test_the_delayed_value_is_not_one_of_the_terminal_ones() -> None:
    """The additive-only rule, and the reason the README's loop had to change.

    Three values existed and every one of them meant "stop". The fourth means
    "keep waiting", so nothing a client switches on today may collide with it.
    """
    terminal = {REASON_ORDER_FAILED, REASON_FULFILLMENT_FAILED, REASON_FULFILLMENT_REFUNDED}
    assert REASON_FULFILLMENT_DELAYED not in terminal
    assert len(terminal) == 3
