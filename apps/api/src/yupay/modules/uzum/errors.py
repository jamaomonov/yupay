"""Uzum Bank Merchant API error catalogue.

Uzum's Merchant API is a set of plain HTTP/JSON endpoints (``/check``
``/create`` ``/confirm`` ``/reverse`` ``/status``): on any business or
transport failure we reply with ``{"status": "FAILED", "errorCode": <int>,
...echo}``, where ``echo`` carries back whichever of
``serviceId``/``transId``/``timestamp`` the request supplied. That body is
unchanged by this module; the route layer (:mod:`yupay.modules.uzum.routes`)
wraps it in a ``JSONResponse`` at HTTP 400 per Uzum's documented contract,
while a success response stays a plain-dict HTTP 200 — this module itself
knows nothing about the wire status code, only the body shape. This module
is pure — no I/O, no DB — and only builds :class:`UzumError` instances
carrying the exact ``errorCode`` Uzum's spec mandates for a given failure.
Service handlers and the route layer raise these and translate them into the
wire response via ``to_response()``.

See ``docs/superpowers/specs/2026-07-22-uzum-merchant-api-design.md`` §8 for
the canonical error catalogue this module implements.
"""

from __future__ import annotations

from typing import Any


class UzumError(Exception):
    """A Uzum Merchant API error, ready to be raised and rendered on the wire.

    Attributes:
        code: The ``errorCode`` Uzum's spec assigns to this failure.
        message: Operator-facing English message describing the failure.
    """

    def __init__(self, code: int, message: str) -> None:
        """Initialize the error.

        Args:
            code: The Uzum ``errorCode``.
            message: Operator-facing English message.
        """
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self, **echo: Any) -> dict[str, Any]:
        """Render this error as the JSON body Uzum expects.

        This only builds the body — it says nothing about the wire status
        code. The route layer wraps this dict in a ``JSONResponse`` at HTTP
        400 (see :func:`yupay.modules.uzum.routes._fail`), per Uzum's
        documented "HTTP 400 on any failure" contract.

        Args:
            **echo: Request fields to echo back verbatim, e.g. ``serviceId``,
                ``transId``, ``timestamp``.

        Returns:
            A dict with ``status``, ``errorCode``, and the echoed fields.
        """
        return {"status": "FAILED", "errorCode": self.code, **echo}


def access_denied() -> UzumError:
    """10001: bad or missing Basic auth credentials."""
    return UzumError(code=10001, message="Access denied")


def bad_json() -> UzumError:
    """10002: the request body is not valid JSON."""
    return UzumError(code=10002, message="JSON parsing error")


def invalid_operation() -> UzumError:
    """10003: the request did not arrive as an HTTP POST."""
    return UzumError(code=10003, message="Invalid operation")


def missing_params() -> UzumError:
    """10005: one or more required parameters are missing."""
    return UzumError(code=10005, message="Missing required parameters")


def invalid_service_id() -> UzumError:
    """10006: the supplied serviceId does not match ours."""
    return UzumError(code=10006, message="Invalid serviceId")


def order_not_found() -> UzumError:
    """10007: no order matches the additional payment attribute (order_id)."""
    return UzumError(code=10007, message="Additional payment attribute not found")


def payment_already_made() -> UzumError:
    """10008: the order has already been paid."""
    return UzumError(code=10008, message="Payment already made")


def payment_cancelled() -> UzumError:
    """10009: the payment for this order was cancelled."""
    return UzumError(code=10009, message="Payment cancelled")


def transaction_already_created() -> UzumError:
    """10010: a transaction with this transId already exists."""
    return UzumError(code=10010, message="Transaction with this transId already created")


def invalid_amount() -> UzumError:
    """10011: the transaction amount does not match the order's price."""
    return UzumError(code=10011, message="Invalid amount")


def amount_below_minimum() -> UzumError:
    """10012: the amount is below the allowed minimum."""
    return UzumError(code=10012, message="Amount below minimum")


def amount_above_maximum() -> UzumError:
    """10013: the amount exceeds the allowed maximum."""
    return UzumError(code=10013, message="Amount exceeds maximum")


def transaction_not_found() -> UzumError:
    """10014: no transaction exists for the given transId."""
    return UzumError(code=10014, message="Transaction transId does not exist")


def transaction_cancelled() -> UzumError:
    """10015: the transaction was cancelled and cannot be confirmed."""
    return UzumError(code=10015, message="Transaction cancelled")


def transaction_already_confirmed() -> UzumError:
    """10016: the transaction has already been confirmed."""
    return UzumError(code=10016, message="Transaction already confirmed")


def transaction_cannot_be_cancelled() -> UzumError:
    """10017: the transaction cannot be cancelled in its current state."""
    return UzumError(code=10017, message="Transaction cannot be cancelled in current state")


def transaction_already_cancelled() -> UzumError:
    """10018: the transaction has already been cancelled."""
    return UzumError(code=10018, message="Transaction already cancelled")


def internal_error() -> UzumError:
    """99999: an unexpected server-side failure occurred while handling the request."""
    return UzumError(code=99999, message="Internal server error")


__all__ = [
    "UzumError",
    "access_denied",
    "amount_above_maximum",
    "amount_below_minimum",
    "bad_json",
    "internal_error",
    "invalid_amount",
    "invalid_operation",
    "invalid_service_id",
    "missing_params",
    "order_not_found",
    "payment_already_made",
    "payment_cancelled",
    "transaction_already_cancelled",
    "transaction_already_confirmed",
    "transaction_already_created",
    "transaction_cancelled",
    "transaction_cannot_be_cancelled",
    "transaction_not_found",
]
