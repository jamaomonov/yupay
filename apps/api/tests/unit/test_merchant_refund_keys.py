"""The refund's ledger key must be incapable of colliding with the charge's.

``wallet.service.post`` replays by ``idempotency_key`` **without comparing
parameters**. A collision therefore does not raise: it returns the charge, and
every caller above treats that transaction as the refund it asked for — the
deposit never moves, ``refunded_usd`` stays ``"0.00"``, and the only symptom is
a reseller who says they were not paid back.

So this is pinned as a property of the two key *families*, not as a naming
convention. If neither prefix is a prefix of the other, then no string built
from one can equal a string built from the other, whatever order ids they
carry — which is the whole claim, proved for every possible id rather than for
the two the author happened to try.
"""

from __future__ import annotations

from yupay.core.ids import new_id
from yupay.modules.merchants.deposit import CHARGE_KEY_PREFIX, charge_key
from yupay.modules.merchants.refund import REFUND_KEY_PREFIX, refund_key


def test_neither_key_family_can_contain_the_other() -> None:
    """The complete proof: two prefixes, neither a prefix of the other.

    ``merchant-order:{id}`` and ``merchant-order-refund:{id}`` diverge at the
    character after ``merchant-order``, before either has reached an id — so
    no id on either side can close the gap. The dangerous shape this refuses
    is a refund key spelled ``merchant-order:refund-{id}``, which *is* a
    charge key with an unusual id and would collide with a charge for an order
    whose id happened to read ``refund-…``.
    """
    assert not CHARGE_KEY_PREFIX.startswith(REFUND_KEY_PREFIX)
    assert not REFUND_KEY_PREFIX.startswith(CHARGE_KEY_PREFIX)


def test_the_two_keys_for_one_order_are_different_strings() -> None:
    """The concrete case the property above generalises."""
    order_id = new_id()
    assert charge_key(order_id) != refund_key(order_id)
    assert charge_key(order_id).endswith(order_id)
    assert refund_key(order_id).endswith(order_id)
