"""Payme (Paycom) Merchant API error catalogue.

Payme's Merchant API is JSON-RPC 2.0: on any business or transport failure we
reply with ``{"error": {"code": <int>, "message": {"ru":..,"uz":..,"en":..},
"data": <field|null>}, "id": <req_id>}``. This module is pure — no I/O, no DB —
and only builds :class:`PaymeError` instances carrying the exact code, the
trilingual message, and the offending field (``data``) that Payme's spec
mandates for a given failure. Service handlers and the JSON-RPC route raise
these and translate them into the wire error object via ``to_rpc_error()``.

See Payme's Merchant API docs for the canonical code list; this module
implements the subset YuPay's integration needs.
"""

from __future__ import annotations

from typing import Any


class PaymeError(Exception):
    """A Payme Merchant API error, ready to be raised and rendered on the wire.

    Attributes:
        code: The JSON-RPC error code Payme's spec assigns to this failure.
        message: Trilingual human-readable message, keyed ``"ru"``, ``"uz"``,
            ``"en"`` — Payme displays this to the cashier/customer.
        data: The name of the offending request field (e.g. ``"order_id"``),
            or ``None`` when the error is not attributable to one field.
    """

    def __init__(self, code: int, message: dict[str, str], data: str | None = None) -> None:
        """Initialize the error.

        Args:
            code: The JSON-RPC error code.
            message: Trilingual message dict with keys ``ru``, ``uz``, ``en``.
            data: Offending field name, or ``None``.
        """
        super().__init__(message.get("en", str(code)))
        self.code = code
        self.message = message
        self.data = data

    def to_rpc_error(self) -> dict[str, Any]:
        """Render this error as the JSON-RPC ``error`` object Payme expects.

        Returns:
            A dict with keys ``code``, ``message`` (the trilingual dict), and
            ``data``.
        """
        return {"code": self.code, "message": self.message, "data": self.data}


def invalid_amount() -> PaymeError:
    """-31001: the transaction amount does not match the order's price."""
    return PaymeError(
        code=-31001,
        message={
            "ru": "Неверная сумма",
            "uz": "Noto'g'ri summa",
            "en": "Invalid amount",
        },
    )


def transaction_not_found() -> PaymeError:
    """-31003: no transaction exists for the given Payme transaction id."""
    return PaymeError(
        code=-31003,
        message={
            "ru": "Транзакция не найдена",
            "uz": "Tranzaksiya topilmadi",
            "en": "Transaction not found",
        },
    )


def cannot_cancel_delivered() -> PaymeError:
    """-31007: the order has already been fulfilled; the transaction can't be cancelled."""
    return PaymeError(
        code=-31007,
        message={
            "ru": "Заказ выполнен. Невозможно отменить транзакцию",
            "uz": "Buyurtma bajarildi. Tranzaksiyani bekor qilib bo'lmaydi",
            "en": "Order already delivered. Cannot cancel transaction",
        },
    )


def operation_not_permitted() -> PaymeError:
    """-31008: the requested state transition is not permitted."""
    return PaymeError(
        code=-31008,
        message={
            "ru": "Невозможно выполнить операцию",
            "uz": "Amalni bajarib bo'lmaydi",
            "en": "Operation not permitted",
        },
    )


def order_not_found() -> PaymeError:
    """-31050: no order matches the ``account.order_id`` supplied by Payme."""
    return PaymeError(
        code=-31050,
        message={
            "ru": "Заказ не найден",
            "uz": "Buyurtma topilmadi",
            "en": "Order not found",
        },
        data="order_id",
    )


def order_not_payable() -> PaymeError:
    """-31051: the order exists but is not in a payable state (or already paid)."""
    return PaymeError(
        code=-31051,
        message={
            "ru": "Заказ недоступен к оплате или уже оплачен",
            "uz": "Buyurtma to'lovga yaroqsiz yoki allaqachon to'langan",
            "en": "Order is not payable or already paid",
        },
        data="order_id",
    )


def unauthorized() -> PaymeError:
    """-32504: the request's Basic Auth credentials failed Payme's merchant check."""
    return PaymeError(
        code=-32504,
        message={
            "ru": "Недостаточно привилегий для выполнения метода",
            "uz": "Metodni bajarish uchun huquqlar yetarli emas",
            "en": "Insufficient privileges to perform this method",
        },
    )


def method_not_post() -> PaymeError:
    """-32300: the JSON-RPC request did not arrive as an HTTP POST."""
    return PaymeError(
        code=-32300,
        message={
            "ru": "Метод не поддерживается",
            "uz": "Metod qo'llab-quvvatlanmaydi",
            "en": "Method not supported",
        },
    )


def bad_json() -> PaymeError:
    """-32700: the request body is not valid JSON."""
    return PaymeError(
        code=-32700,
        message={
            "ru": "Ошибка при разборе JSON",
            "uz": "JSON tahlilida xatolik",
            "en": "Error parsing JSON",
        },
    )


def bad_rpc_fields() -> PaymeError:
    """-32600: the JSON-RPC envelope is missing or has malformed required fields."""
    return PaymeError(
        code=-32600,
        message={
            "ru": "Неверный запрос",
            "uz": "Noto'g'ri so'rov",
            "en": "Invalid request",
        },
    )


def method_not_found() -> PaymeError:
    """-32601: the ``method`` field names a JSON-RPC method we don't implement."""
    return PaymeError(
        code=-32601,
        message={
            "ru": "Метод не найден",
            "uz": "Metod topilmadi",
            "en": "Method not found",
        },
    )


def internal_error() -> PaymeError:
    """-32400: an unexpected server-side failure occurred while handling the request."""
    return PaymeError(
        code=-32400,
        message={
            "ru": "Внутренняя ошибка сервера",
            "uz": "Server ichki xatosi",
            "en": "Internal server error",
        },
    )


def fiscal_receipt_not_found() -> PaymeError:
    """-32001: no fiscal receipt exists for the requested transaction."""
    return PaymeError(
        code=-32001,
        message={
            "ru": "Фискальный чек не найден",
            "uz": "Fiskal chek topilmadi",
            "en": "Fiscal receipt not found",
        },
    )


__all__ = [
    "PaymeError",
    "bad_json",
    "bad_rpc_fields",
    "cannot_cancel_delivered",
    "fiscal_receipt_not_found",
    "internal_error",
    "invalid_amount",
    "method_not_found",
    "method_not_post",
    "operation_not_permitted",
    "order_not_found",
    "order_not_payable",
    "transaction_not_found",
    "unauthorized",
]
