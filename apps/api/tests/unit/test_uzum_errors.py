"""Unit tests for the Uzum Bank Merchant API error catalogue.

Pure module — every factory must return a :class:`UzumError` with the exact
``errorCode`` Uzum's Merchant API spec mandates, and ``to_response()`` must
render the exact wire shape the ``/check`` `/create`` `/confirm`` `/reverse``
`/status`` handlers reply with: ``{"status": "FAILED", "errorCode": <int>,
**echo}`` where ``echo`` carries back whichever of ``serviceId``/``transId``/
``timestamp`` the request supplied.
"""

from __future__ import annotations

import pytest
from yupay.modules.uzum.errors import (
    UzumError,
    access_denied,
    amount_above_maximum,
    amount_below_minimum,
    bad_json,
    internal_error,
    invalid_amount,
    invalid_operation,
    invalid_service_id,
    missing_params,
    order_not_found,
    payment_already_made,
    payment_cancelled,
    transaction_already_cancelled,
    transaction_already_confirmed,
    transaction_already_created,
    transaction_cancelled,
    transaction_cannot_be_cancelled,
    transaction_not_found,
)

ALL_FACTORIES_AND_CODES = (
    (access_denied, 10001),
    (bad_json, 10002),
    (invalid_operation, 10003),
    (missing_params, 10005),
    (invalid_service_id, 10006),
    (order_not_found, 10007),
    (payment_already_made, 10008),
    (payment_cancelled, 10009),
    (transaction_already_created, 10010),
    (invalid_amount, 10011),
    (amount_below_minimum, 10012),
    (amount_above_maximum, 10013),
    (transaction_not_found, 10014),
    (transaction_cancelled, 10015),
    (transaction_already_confirmed, 10016),
    (transaction_cannot_be_cancelled, 10017),
    (transaction_already_cancelled, 10018),
    (internal_error, 99999),
)


@pytest.mark.parametrize(("factory", "code"), ALL_FACTORIES_AND_CODES)
def test_factory_code(factory: object, code: int) -> None:
    err = factory()  # type: ignore[operator]
    assert isinstance(err, UzumError)
    assert isinstance(err, Exception)
    assert err.code == code
    assert isinstance(err.message, str)
    assert err.message  # non-empty


def test_order_not_found_code() -> None:
    assert order_not_found().code == 10007


def test_to_response_shape() -> None:
    r = invalid_amount().to_response(serviceId=101202, transId="t")
    assert r == {"status": "FAILED", "errorCode": 10011, "serviceId": 101202, "transId": "t"}


def test_to_response_no_echo() -> None:
    r = internal_error().to_response()
    assert r == {"status": "FAILED", "errorCode": 99999}


def test_to_response_echoes_arbitrary_kwargs() -> None:
    r = order_not_found().to_response(serviceId=1, timestamp=1234567890)
    assert r == {
        "status": "FAILED",
        "errorCode": 10007,
        "serviceId": 1,
        "timestamp": 1234567890,
    }


def test_uzum_error_is_raisable() -> None:
    with pytest.raises(UzumError) as exc_info:
        raise invalid_amount()
    assert exc_info.value.code == 10011


def test_uzum_error_constructor_direct() -> None:
    err = UzumError(code=1, message="custom message")
    assert err.code == 1
    assert err.message == "custom message"
    assert err.to_response() == {"status": "FAILED", "errorCode": 1}
