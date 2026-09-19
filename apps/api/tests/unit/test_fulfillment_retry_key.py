"""A retry must reach the supplier — without ever buying the goods twice.

The fulfilment idempotency key was ``task.id``, fixed for the life of the
task. NOVA burns a key the moment it sees one and answers a reuse with
``409 "This Idempotency-Key was already used for a purchase"``, so a NOVA
task that failed once could never be retried. That is not an edge case: it
is precisely what a low-balance stall asks an operator to do — park the
order, top up, press Retry — and the 409 it got back graded as ``UNKNOWN``,
which the confidence ladder never lets go of. One press turned "we know we
spent nothing" into "we cannot tell", permanently.

The other adapters are the reason this is a list of exceptions rather than
a new default: Waxpeer returns the *original* top-up for a repeated
``custom_id`` and G-Engine recovers an order by the same ``uuid``. For them
the reuse is the protection, and minting a fresh key would pay twice.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome


def _task(supplier: str, **extra: object) -> FulfillmentTask:
    """The three fields the key logic reads, and nothing else.

    A real ``FulfillmentTask`` would drag in the whole mapper registry —
    Order, Payment, Sku — for no gain: neither function under test touches a
    relationship or the database.
    """
    return cast(
        FulfillmentTask,
        SimpleNamespace(id=new_id(), supplier=supplier, extra_metadata=dict(extra)),
    )


def test_an_untouched_task_sends_its_own_id() -> None:
    task = _task("nova")
    assert ff_svc.idempotency_key_for(task) == task.id


def test_a_nova_retry_gets_a_key_the_supplier_has_not_seen() -> None:
    task = _task("nova")
    before = ff_svc.idempotency_key_for(task)

    ff_svc.arm_retry_key(task)

    after = ff_svc.idempotency_key_for(task)
    assert after != before
    assert after.startswith(f"{task.id}:")


def test_two_retries_do_not_repeat_a_key() -> None:
    """A second Retry after a second failure must not replay the first key."""
    task = _task("nova")
    ff_svc.arm_retry_key(task)
    first = ff_svc.idempotency_key_for(task)
    ff_svc.arm_retry_key(task)

    assert ff_svc.idempotency_key_for(task) != first


@pytest.mark.parametrize("supplier", ["waxpeer", "gengine", "g2b"])
def test_a_supplier_that_replays_on_the_key_keeps_it(supplier: str) -> None:
    """Changing the key for these would buy the goods a second time."""
    task = _task(supplier)

    ff_svc.arm_retry_key(task)

    assert ff_svc.idempotency_key_for(task) == task.id


@pytest.mark.parametrize("standing", [MoneyOutcome.UNKNOWN, MoneyOutcome.SPENT])
def test_no_fresh_key_once_an_attempt_may_have_spent(standing: MoneyOutcome) -> None:
    """The one mistake worse than a stuck task.

    A key NOVA has not seen is a new purchase. If an earlier attempt may
    already have bought the goods, that is how the customer's order gets paid
    for twice — so these keep the burned key, the supplier refuses it, and a
    human reconciles instead.
    """
    task = _task("nova", money_outcome=standing.value)

    ff_svc.arm_retry_key(task)

    assert ff_svc.idempotency_key_for(task) == task.id


def test_a_returned_outcome_may_still_be_retried() -> None:
    """``RETURNED`` is "the money is with us" — nothing to double-charge."""
    task = _task("nova", money_outcome=MoneyOutcome.RETURNED.value)

    ff_svc.arm_retry_key(task)

    assert ff_svc.idempotency_key_for(task) != task.id
