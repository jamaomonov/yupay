"""The debit's ledger key must be incapable of colliding with the other three.

``wallet.service.post`` replays by ``idempotency_key`` **without comparing
parameters**, so a collision does not raise: it hands the caller an existing
transaction and every caller above treats it as the debit it asked for. The
balance never moves, the response echoes somebody else's amount, and the only
symptom is a merchant whose money is still there.

Pinned as a property of the key *families* rather than as a naming
convention, for the reason ``test_merchant_refund_keys`` pins its own: if no
prefix is a prefix of another, then no string built from one can equal a
string built from another, whatever merchant or order ids they carry — proved
for every possible id rather than for the two the author happened to try.
"""

from __future__ import annotations

import itertools

from yupay.core.ids import new_id
from yupay.modules.merchants.debit import DEBIT_KEY_PREFIX, debit_key
from yupay.modules.merchants.deposit import CHARGE_KEY_PREFIX, charge_key
from yupay.modules.merchants.refund import REFUND_KEY_PREFIX, refund_key

#: The credit's namespace is built inline by ``admin_routes.credit_deposit``
#: rather than by a function, so it is spelled here to be compared. The
#: integration test is what pins that the route still uses it; this file pins
#: that the four families cannot meet.
CREDIT_KEY_PREFIX = "merchant-credit:"

_ALL_PREFIXES = (CHARGE_KEY_PREFIX, REFUND_KEY_PREFIX, CREDIT_KEY_PREFIX, DEBIT_KEY_PREFIX)


def test_no_key_family_can_contain_another() -> None:
    """The complete proof: four prefixes, none a prefix of another.

    The dangerous shape this refuses is a debit key spelled
    ``merchant-credit:debit-{id}``, which *is* a credit key with an unusual
    client key and would collide with a credit whose operator happened to
    type ``debit-…``.
    """
    for a, b in itertools.permutations(_ALL_PREFIXES, 2):
        assert not a.startswith(b), f"{a!r} starts with {b!r}"


def test_the_four_prefixes_are_distinct() -> None:
    """A permutation check passes vacuously if two prefixes are equal."""
    assert len(set(_ALL_PREFIXES)) == len(_ALL_PREFIXES)


def test_a_debit_key_is_scoped_to_its_merchant() -> None:
    """Two merchants reusing one operator key get two ledger keys.

    The client half is whatever the operator's UI sent, so it is not unique
    across merchants on its own. Without the merchant in the key, zeroing two
    balances in a row from one form would debit the first merchant twice and
    the second not at all.
    """
    client_key = "zero-the-test-balance"
    first, second = new_id(), new_id()
    assert debit_key(first, client_key) != debit_key(second, client_key)
    assert debit_key(first, client_key).startswith(DEBIT_KEY_PREFIX)


def test_one_id_cannot_produce_two_equal_keys() -> None:
    """The concrete case the property above generalises."""
    some_id = new_id()
    keys = {
        charge_key(some_id),
        refund_key(some_id),
        debit_key(some_id, some_id),
        f"{CREDIT_KEY_PREFIX}{some_id}:{some_id}",
    }
    assert len(keys) == 4
