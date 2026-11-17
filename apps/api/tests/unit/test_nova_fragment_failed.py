"""A failed Fragment order that never paid Telegram can be retried.

Every NOVA Telegram failure on production 2026-11-05..14 was ``FAILED`` with
``tx_hash: null`` — their «could not be completed» or «Insufficient account
balance.» — and each ended in a manual delivery: graded ``UNKNOWN``, Retry kept
the old key, and Fragment answered it with the same dead order.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.fulfillment.suppliers.nova_grading import _finish, _result


def _order(**over: Any) -> dict[str, Any]:
    """The shape their Fragment API answered on production, recipient left out."""
    base: dict[str, Any] = {
        "id": "764e1685-63a3-429d-a627-0290d9405087",
        "kind": "STARS",
        "status": "FAILED",
        "stars_amount": 50,
        "customer_amount_usd": None,
        "tx_hash": None,
        "error": "The Telegram Stars order could not be completed. Please try again later.",
    }
    base.update(over)
    return base


def test_a_failed_order_with_no_transaction_spent_nothing() -> None:
    result = _result(_order())

    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.RETURNED
    assert "needs_reconciliation" not in result.extra_metadata
    assert "could not be completed" in (result.error or "")


def test_our_low_balance_is_the_same_story() -> None:
    result = _finish(_order(error="Insufficient account balance.", customer_amount_usd="53.2875"))

    assert result.money_outcome is MoneyOutcome.RETURNED


def test_a_failed_order_that_did_send_a_transaction_stays_open() -> None:
    """Something left their wallet: a human looks before we buy again."""
    result = _result(_order(tx_hash="abc123"))

    assert result.money_outcome is MoneyOutcome.UNKNOWN


def test_a_failed_v2_order_is_not_touched() -> None:
    """The games API carries no tx_hash; its grading is unchanged."""
    result = _result({"id": "o-1", "kind": "topup", "status": "failed"})

    assert result.money_outcome is MoneyOutcome.UNKNOWN


def test_so_retry_now_sends_a_fresh_key() -> None:
    task = cast(FulfillmentTask, SimpleNamespace(id=new_id(), supplier="nova", extra_metadata={}))
    ff_svc.record_money_outcome(task, _result(_order()).money_outcome or MoneyOutcome.UNKNOWN)

    ff_svc.arm_retry_key(task)

    assert ff_svc.idempotency_key_for(task) != task.id
