"""Unit tests for ``orders.validation.validate_fulfillment_data``.

Focused on the checkout-side ReDoS mitigation: ``pattern`` is admin-authored
and run inline via ``re.fullmatch`` with no timeout, so before matching we
cap the input length — a short bound sharply limits how much work any
backtracking regex engine can do, independent of how "safe" the pattern
itself looks.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.orders.validation import validate_fulfillment_data


def _product(pattern: str = r"^[0-9]{6,20}$") -> SimpleNamespace:
    return SimpleNamespace(
        required_fields=[
            {
                "key": "player_id",
                "type": "text",
                "required": True,
                "pattern": pattern,
            }
        ]
    )


def test_matching_value_is_accepted() -> None:
    cleaned = validate_fulfillment_data(product=_product(), data={"player_id": "123456"})
    assert cleaned == {"player_id": "123456"}


def test_non_matching_value_rejected_with_pattern_reason() -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_fulfillment_data(product=_product(), data={"player_id": "abc"})
    assert exc_info.value.extra["extra"]["reason"] == "pattern"


def test_overlong_value_is_rejected_before_matching() -> None:
    """A value longer than the cap is refused fast, never reaching ``re.fullmatch``.

    Uses a pattern that *would* otherwise match a long run of digits, to
    prove the length cap — not the pattern — is what trips.
    """
    overlong_digits = "1" * 300
    with pytest.raises(ValidationError) as exc_info:
        validate_fulfillment_data(
            product=_product(pattern=r"^[0-9]+$"), data={"player_id": overlong_digits}
        )
    assert exc_info.value.extra["extra"]["reason"] == "length"


def test_value_at_the_boundary_is_still_checked_against_the_pattern() -> None:
    """Right at the cap, the value still has to satisfy the actual pattern."""
    at_cap_but_wrong_shape = "a" * 256
    with pytest.raises(ValidationError) as exc_info:
        validate_fulfillment_data(
            product=_product(pattern=r"^[0-9]+$"), data={"player_id": at_cap_but_wrong_shape}
        )
    assert exc_info.value.extra["extra"]["reason"] == "pattern"


def test_a_pathological_pattern_never_reaches_re_fullmatch_when_input_is_capped() -> None:
    """Simulates a nested-quantifier pattern that slipped past write-time checks.

    ``(a+)+$`` is the textbook catastrophic-backtracking shape: fed a long
    run of ``a``s with no trailing match, a backtracking engine can take
    exponential time. The length cap must reject the over-long input
    *before* ``re.fullmatch`` ever runs it — proving that by using an input
    long enough that, if the cap were missing, this test would hang instead
    of completing.
    """
    data: dict[str, Any] = {"player_id": "a" * 300 + "!"}
    with pytest.raises(ValidationError) as exc_info:
        validate_fulfillment_data(product=_product(pattern=r"^(a+)+$"), data=data)
    assert exc_info.value.extra["extra"]["reason"] == "length"
