"""``Actor``'s exactly-one-of-three rule — the Python half of the actor invariant.

The database has enforced exactly-one-of-three since migration 0066
(``ck_orders_actor_exclusive``: user, guest email, or merchant). These tests pin
the service-layer value object to the same shape, so a bad actor is refused
before it ever reaches a flush — and, just as importantly, so the two retail
arms keep behaving exactly as they did when there were only two of them.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.orders.service import Actor


def test_actor_accepts_a_merchant_arm() -> None:
    """The new third arm: a B2B reseller placing an order through its own key."""
    a = Actor(user_id=None, email=None, merchant_id="m1")
    assert a.merchant_id == "m1"
    assert a.user_id is None
    assert a.email is None


def test_actor_accepts_a_user_arm_without_naming_the_merchant() -> None:
    """Retail call sites pass two arguments and must keep working untouched."""
    a = Actor(user_id="u1", email=None)
    assert a.user_id == "u1"
    assert a.merchant_id is None


def test_actor_accepts_a_guest_arm_without_naming_the_merchant() -> None:
    """The guest half of the same guarantee."""
    a = Actor(user_id=None, email="g@example.test")
    assert a.email == "g@example.test"
    assert a.merchant_id is None


@pytest.mark.parametrize(
    ("user_id", "email", "merchant_id"),
    [
        ("u1", None, "m1"),
        (None, "g@example.test", "m1"),
        ("u1", "g@example.test", None),
        ("u1", "g@example.test", "m1"),
    ],
    ids=["user+merchant", "guest+merchant", "user+guest", "all-three"],
)
def test_actor_still_rejects_two_arms(
    user_id: str | None, email: str | None, merchant_id: str | None
) -> None:
    """Any combination of more than one arm is refused, as the DB CHECK refuses it."""
    with pytest.raises(ValidationError):
        Actor(user_id=user_id, email=email, merchant_id=merchant_id)


def test_actor_still_rejects_zero_arms() -> None:
    """An order with nobody to own it is refused here, not at the flush."""
    with pytest.raises(ValidationError):
        Actor(user_id=None, email=None)


def test_actor_still_rejects_zero_arms_when_the_merchant_is_named_none() -> None:
    """Spelling the third arm out explicitly changes nothing."""
    with pytest.raises(ValidationError):
        Actor(user_id=None, email=None, merchant_id=None)


def test_actor_is_still_frozen() -> None:
    """A value object: an order's owner cannot be swapped after construction.

    Worth pinning because ``__post_init__`` only runs once — a mutable ``Actor``
    could be re-pointed at a second arm behind the validation's back.
    """
    a = Actor(user_id=None, email=None, merchant_id="m1")
    with pytest.raises(FrozenInstanceError):
        a.merchant_id = "m2"  # type: ignore[misc]
