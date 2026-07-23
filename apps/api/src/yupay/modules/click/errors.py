"""Click Shop API error catalogue.

Click's Shop API is a set of plain HTTP/JSON endpoints (``/prepare``
``/complete``): on any business or transport failure we reply at HTTP 200
with ``{"error": <int>, "error_note": <str>, ...echo}``, where ``echo``
carries back whichever of ``click_trans_id``/``merchant_trans_id`` the
request supplied. This module is pure — no I/O, no DB — and only builds
:class:`ClickError` instances carrying the exact ``error``/``error_note``
pair Click's spec mandates for a given failure. Service handlers and the
route layer raise these and translate them into the wire response via
``to_response()``.

This is the inverted-webhook twin of :mod:`yupay.modules.uzum.errors` — Click
uses ``error``/``error_note`` on the wire instead of Uzum's
``status``/``errorCode``, and the success case (``0``/``Success``) is
rendered directly by handlers, not via a factory here.

See ``docs/superpowers/specs/2026-07-23-click-shop-api-design.md`` §8 for the
canonical error catalogue this module implements.
"""

from __future__ import annotations

from typing import Any


class ClickError(Exception):
    """A Click Shop API error, ready to be raised and rendered on the wire.

    Attributes:
        code: The ``error`` code Click's spec assigns to this failure.
        note: Operator-facing English message describing the failure.
    """

    def __init__(self, code: int, note: str) -> None:
        """Initialize the error.

        Args:
            code: The Click ``error`` code.
            note: Operator-facing English message.
        """
        super().__init__(note)
        self.code = code
        self.note = note

    def to_response(self, **echo: Any) -> dict[str, Any]:
        """Render this error as the JSON body Click expects.

        Args:
            **echo: Request fields to echo back verbatim, e.g.
                ``click_trans_id``, ``merchant_trans_id``.

        Returns:
            A dict with ``error``, ``error_note``, and the echoed fields.
        """
        return {"error": self.code, "error_note": self.note, **echo}


def sign_check_failed() -> ClickError:
    """-1: signature mismatch or unknown service."""
    return ClickError(code=-1, note="SIGN CHECK FAILED!")


def incorrect_amount() -> ClickError:
    """-2: amount does not match the order/transaction amount."""
    return ClickError(code=-2, note="Incorrect parameter amount")


def action_not_found() -> ClickError:
    """-3: action is not 0 or 1."""
    return ClickError(code=-3, note="Action not found")


def already_paid() -> ClickError:
    """-4: Complete called on an already-confirmed transaction."""
    return ClickError(code=-4, note="Already paid")


def user_not_found() -> ClickError:
    """-5: merchant_trans_id (order) not found."""
    return ClickError(code=-5, note="User does not exist")


def transaction_not_found() -> ClickError:
    """-6: merchant_prepare_id not found."""
    return ClickError(code=-6, note="Transaction does not exist")


def failed_to_update() -> ClickError:
    """-7: internal update failure."""
    return ClickError(code=-7, note="Failed to update user")


def bad_request() -> ClickError:
    """-8: malformed request from Click."""
    return ClickError(code=-8, note="Error in request from click")


def transaction_cancelled() -> ClickError:
    """-9: transaction cancelled (Click abort / negative inbound error / stale)."""
    return ClickError(code=-9, note="Transaction cancelled")


__all__ = [
    "ClickError",
    "action_not_found",
    "already_paid",
    "bad_request",
    "failed_to_update",
    "incorrect_amount",
    "sign_check_failed",
    "transaction_cancelled",
    "transaction_not_found",
    "user_not_found",
]
