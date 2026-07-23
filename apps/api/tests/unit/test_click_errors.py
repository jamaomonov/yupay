"""Unit tests for the Click Shop API error catalogue.

Pure module — every factory must return a :class:`ClickError` with the exact
``error``/``error_note`` pair Click's Shop API spec mandates, and
``to_response()`` must render the exact wire shape the ``/prepare``
``/complete`` handlers reply with: ``{"error": <int>, "error_note": <str>,
**echo}`` where ``echo`` carries back whichever of ``click_trans_id``/
``merchant_trans_id`` the request supplied.
"""

from __future__ import annotations

import pytest
from yupay.modules.click.errors import (
    ClickError,
    action_not_found,
    already_paid,
    bad_request,
    failed_to_update,
    incorrect_amount,
    sign_check_failed,
    transaction_cancelled,
    transaction_not_found,
    user_not_found,
)

ALL_FACTORIES_AND_CODES_AND_NOTES = (
    (sign_check_failed, -1, "SIGN CHECK FAILED!"),
    (incorrect_amount, -2, "Incorrect parameter amount"),
    (action_not_found, -3, "Action not found"),
    (already_paid, -4, "Already paid"),
    (user_not_found, -5, "User does not exist"),
    (transaction_not_found, -6, "Transaction does not exist"),
    (failed_to_update, -7, "Failed to update user"),
    (bad_request, -8, "Error in request from click"),
    (transaction_cancelled, -9, "Transaction cancelled"),
)


@pytest.mark.parametrize(("factory", "code", "note"), ALL_FACTORIES_AND_CODES_AND_NOTES)
def test_factory_code_and_note(factory: object, code: int, note: str) -> None:
    err = factory()  # type: ignore[operator]
    assert isinstance(err, ClickError)
    assert isinstance(err, Exception)
    assert err.code == code
    assert err.note == note


def test_to_response_shape() -> None:
    r = incorrect_amount().to_response(click_trans_id=1, merchant_trans_id="o")
    assert r == {
        "error": -2,
        "error_note": "Incorrect parameter amount",
        "click_trans_id": 1,
        "merchant_trans_id": "o",
    }


def test_to_response_no_echo() -> None:
    r = sign_check_failed().to_response()
    assert r == {"error": -1, "error_note": "SIGN CHECK FAILED!"}


def test_to_response_echoes_arbitrary_kwargs() -> None:
    r = user_not_found().to_response(merchant_trans_id="o", click_trans_id=99)
    assert r == {
        "error": -5,
        "error_note": "User does not exist",
        "merchant_trans_id": "o",
        "click_trans_id": 99,
    }


def test_click_error_is_raisable() -> None:
    with pytest.raises(ClickError) as exc_info:
        raise transaction_not_found()
    assert exc_info.value.code == -6


def test_click_error_constructor_direct() -> None:
    err = ClickError(code=-100, note="custom note")
    assert err.code == -100
    assert err.note == "custom note"
    assert err.to_response() == {"error": -100, "error_note": "custom note"}
