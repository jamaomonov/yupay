"""Unit tests for the Payme (Paycom) Merchant API error catalogue.

Pure module — every factory must return a :class:`PaymeError` with the exact
JSON-RPC 2.0 error code Payme's spec mandates, and ``to_rpc_error()`` must
render the exact wire shape services and the JSON-RPC route rely on:
``{"code": int, "message": {"ru": str, "uz": str, "en": str}, "data": str | None}``.
"""

from __future__ import annotations

import pytest
from yupay.modules.payme.errors import (
    PaymeError,
    bad_json,
    bad_rpc_fields,
    cannot_cancel_delivered,
    fiscal_receipt_not_found,
    internal_error,
    invalid_amount,
    method_not_found,
    method_not_post,
    operation_not_permitted,
    order_has_pending_transaction,
    order_not_found,
    order_not_payable,
    transaction_not_found,
    unauthorized,
)


def _assert_localized_message(message: dict[str, str]) -> None:
    assert set(message.keys()) == {"ru", "uz", "en"}
    for locale in ("ru", "uz", "en"):
        assert isinstance(message[locale], str)
        assert message[locale]  # non-empty


def test_invalid_amount_code_and_message() -> None:
    err = invalid_amount()
    assert isinstance(err, PaymeError)
    assert isinstance(err, Exception)
    assert err.code == -31001
    _assert_localized_message(err.message)
    assert err.data is None


def test_transaction_not_found_code() -> None:
    assert transaction_not_found().code == -31003


def test_cannot_cancel_delivered_code() -> None:
    assert cannot_cancel_delivered().code == -31007


def test_operation_not_permitted_code() -> None:
    assert operation_not_permitted().code == -31008


def test_order_not_found_code_and_data() -> None:
    err = order_not_found()
    assert err.code == -31050
    assert err.data == "order_id"
    _assert_localized_message(err.message)


def test_order_has_pending_transaction_code_and_data() -> None:
    err = order_has_pending_transaction()
    # Must fall in Payme's account-error range so the sandbox's "new
    # transaction on a busy order" case passes.
    assert -31099 <= err.code <= -31050
    assert err.data == "order_id"
    _assert_localized_message(err.message)


def test_order_not_payable_code_and_data() -> None:
    err = order_not_payable()
    assert err.code == -31051
    assert err.data == "order_id"
    _assert_localized_message(err.message)


def test_unauthorized_code() -> None:
    assert unauthorized().code == -32504


def test_method_not_post_code() -> None:
    assert method_not_post().code == -32300


def test_bad_json_code() -> None:
    assert bad_json().code == -32700


def test_bad_rpc_fields_code() -> None:
    assert bad_rpc_fields().code == -32600


def test_method_not_found_code() -> None:
    assert method_not_found().code == -32601


def test_internal_error_code() -> None:
    assert internal_error().code == -32400


def test_fiscal_receipt_not_found_code() -> None:
    assert fiscal_receipt_not_found().code == -32001


def test_non_order_errors_have_no_data() -> None:
    for factory in (
        invalid_amount,
        transaction_not_found,
        cannot_cancel_delivered,
        operation_not_permitted,
        unauthorized,
        method_not_post,
        bad_json,
        bad_rpc_fields,
        method_not_found,
        internal_error,
        fiscal_receipt_not_found,
    ):
        assert factory().data is None


def test_to_rpc_error_shape() -> None:
    err = invalid_amount()
    rpc = err.to_rpc_error()
    assert set(rpc.keys()) == {"code", "message", "data"}
    assert rpc["code"] == -31001
    assert rpc["data"] is None
    _assert_localized_message(rpc["message"])


def test_invalid_amount_to_rpc_error_code() -> None:
    assert invalid_amount().to_rpc_error()["code"] == -31001


def test_order_not_found_to_rpc_error_data() -> None:
    rpc = order_not_found().to_rpc_error()
    assert rpc["code"] == -31050
    assert rpc["data"] == "order_id"


def test_payme_error_is_raisable() -> None:
    with pytest.raises(PaymeError) as exc_info:
        raise invalid_amount()
    assert exc_info.value.code == -31001


def test_payme_error_constructor_direct() -> None:
    err = PaymeError(code=-1, message={"ru": "р", "uz": "u", "en": "e"}, data="x")
    assert err.code == -1
    assert err.message == {"ru": "р", "uz": "u", "en": "e"}
    assert err.data == "x"
    assert err.to_rpc_error() == {
        "code": -1,
        "message": {"ru": "р", "uz": "u", "en": "e"},
        "data": "x",
    }
