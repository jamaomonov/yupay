"""Paynet UWS error catalogue (UWS v3.4, «Порядок технического взаимодействия» §8).

Two numbering schemes share one ``error`` object and are routinely confused:

* **Paynet's own codes** (``0``, ``77``, ``100``–``415``, ``501``–``603``) are
  business outcomes. The HTTP status stays **200** — these are not HTTP codes.
* **JSON-RPC codes** (``-32700``…``-32603``) are protocol failures.

The one thing that is *not* in this file is a failed login. Paynet's spec is
explicit that bad or missing Basic credentials must be answered **HTTP 401**
with no body, not a 200 carrying an error object — which is where this differs
from Payme, whose spec demands the opposite. Legacy code ``412`` exists for it
and is deliberately unused.

Every message is trilingual: the payer sees it inside the Paynet app, and that
payer is in Uzbekistan.
"""

from __future__ import annotations

from typing import Any, Final

#: Paynet reads ``message`` as a single string. Russian is what their terminal
#: and app show today; the other two are carried so a future locale-aware
#: response costs a lookup rather than a translation round.
Message = dict[str, str]


class PaynetError(Exception):
    """A UWS error, renderable as the JSON-RPC ``error`` object.

    Args:
        code: Paynet business code, or a JSON-RPC protocol code.
        message: Trilingual text; ``ru`` is what goes on the wire.
    """

    def __init__(self, code: int, message: Message) -> None:
        self.code = code
        self.message = message
        super().__init__(f"paynet error {code}: {message['ru']}")

    def to_rpc_error(self) -> dict[str, Any]:
        """Render as ``{"code", "message"}`` for the JSON-RPC envelope."""
        return {"code": self.code, "message": self.message["ru"]}


def _err(code: int, ru: str, uz: str, en: str) -> PaynetError:
    return PaynetError(code, {"ru": ru, "uz": uz, "en": en})


# --- account / order lookup -------------------------------------------------
#
# Paynet's catalogue was written for utility billing, where an account either
# exists or does not. An order has more states than that, so the mapping below
# is a decision rather than a translation, and it is the one an operator will
# read off a terminal receipt:
#
#   302  the order id does not exist at all       — "клиент не найден"
#   201  the order exists and is already paid     — "транзакция уже существует"
#   501  the order exists but cannot be paid now  — expired, cancelled, on hold
#
# 501 is the honest home for the third case: Paynet words it "транзакции
# запрещены для данного плательщика", which is exactly what an expired order
# is. Splitting it out from 302 matters because the two need different answers
# from support — "check the number" versus "place the order again".

ORDER_NOT_FOUND: Final = 302
ORDER_ALREADY_PAID: Final = 201
ORDER_NOT_PAYABLE: Final = 501


def order_not_found() -> PaynetError:
    """``302`` — no order carries the ``order_id`` that was sent."""
    return _err(
        ORDER_NOT_FOUND,
        "Заказ не найден. Проверьте номер заказа.",
        "Buyurtma topilmadi. Buyurtma raqamini tekshiring.",
        "Order not found. Check the order number.",
    )


def order_already_paid() -> PaynetError:
    """``201`` — the order is paid; a second payment would be a double charge."""
    return _err(
        ORDER_ALREADY_PAID,
        "Заказ уже оплачен.",
        "Buyurtma allaqachon toʻlangan.",
        "The order is already paid.",
    )


def order_not_payable() -> PaynetError:
    """``501`` — the order exists but is expired, cancelled or on hold."""
    return _err(
        ORDER_NOT_PAYABLE,
        "Заказ больше не ожидает оплаты. Оформите новый заказ.",
        "Buyurtma endi toʻlov kutmayapti. Yangi buyurtma rasmiylashtiring.",
        "The order is no longer awaiting payment. Please place a new one.",
    )


# --- amount -----------------------------------------------------------------

INVALID_AMOUNT: Final = 413
AMOUNT_OVER_LIMIT: Final = 415
INVALID_DATETIME: Final = 414


def invalid_amount() -> PaynetError:
    """``413`` — the amount does not match what the order is owed, to the tiyin."""
    return _err(
        INVALID_AMOUNT,
        "Неверная сумма платежа.",
        "Toʻlov summasi notoʻgʻri.",
        "Invalid payment amount.",
    )


def invalid_datetime() -> PaynetError:
    """``414`` — a ``GetStatement`` window bound is not in the documented format."""
    return _err(
        INVALID_DATETIME,
        "Неверный формат даты и времени.",
        "Sana va vaqt formati notoʻgʻri.",
        "Invalid date/time format.",
    )


def amount_over_limit() -> PaynetError:
    """``415`` — above the per-transaction ceiling."""
    return _err(
        AMOUNT_OVER_LIMIT,
        "Сумма превышает максимальный лимит.",
        "Summa maksimal limitdan oshib ketdi.",
        "The amount exceeds the maximum limit.",
    )


# --- transaction lifecycle --------------------------------------------------

TRANSACTION_NOT_FOUND: Final = 203
CANCEL_REFUSED: Final = 306
# 202 ("транзакция уже отменена") is in Paynet's catalogue and deliberately
# unused here. Paynet retries a cancel it never got an answer to, so a second
# CancelTransaction for the same id is far more likely to be a retry than an
# operator asking twice — and answering an error to a retry reads as a failed
# reversal. We echo the stored state 2 instead, which is both true and
# idempotent. See README.


def transaction_not_found() -> PaynetError:
    """``203`` — unknown ``transactionId``.

    ``CancelTransaction`` only. ``CheckTransaction`` must answer a successful
    envelope carrying ``transactionState: 3`` instead — the spec is explicit,
    and answering 203 there makes Paynet treat a routine "do you know this?"
    as a failure.
    """
    return _err(
        TRANSACTION_NOT_FOUND,
        "Транзакция не найдена.",
        "Tranzaksiya topilmadi.",
        "Transaction not found.",
    )


def cancel_refused_delivered() -> PaynetError:
    """``306`` — goods already handed over, so we refuse the reversal.

    Paynet documents ``306`` as the supplier refusing a return under its own
    business rules. A delivered voucher code is exactly that: the customer
    holds it, and clawing the money back would hand them the goods for free.
    Such a case is settled by a human, never by this endpoint.
    """
    return _err(
        CANCEL_REFUSED,
        "Отмена невозможна: товар уже выдан. Обратитесь в поддержку.",
        "Bekor qilib boʻlmaydi: tovar allaqachon berilgan. Qoʻllab-quvvatlashga murojaat qiling.",
        "Cannot cancel: the goods were already delivered. Contact support.",
    )


# --- service-level ----------------------------------------------------------

UNKNOWN_SERVICE: Final = 305
SYSTEM_ERROR: Final = 102


def unknown_service() -> PaynetError:
    """``305`` — ``serviceId`` is not the one we are contracted under."""
    return _err(
        UNKNOWN_SERVICE,
        "Услуга не найдена.",
        "Xizmat topilmadi.",
        "Service not found.",
    )


def system_error() -> PaynetError:
    """``102`` — we broke. Paynet retries; the payer sees a generic failure."""
    return _err(
        SYSTEM_ERROR,
        "Системная ошибка. Попробуйте позже.",
        "Tizim xatosi. Keyinroq urinib koʻring.",
        "System error. Please try again later.",
    )


# --- JSON-RPC protocol ------------------------------------------------------


def bad_json() -> PaynetError:
    """``-32700`` — the body is not valid JSON."""
    return _err(
        -32700,
        "Ошибка разбора JSON.",
        "JSON tahlil qilishda xato.",
        "Parse error.",
    )


def bad_rpc_fields() -> PaynetError:
    """``-32600`` — the envelope is missing or mistyping a required field."""
    return _err(
        -32600,
        "Некорректный запрос.",
        "Notoʻgʻri soʻrov.",
        "Invalid request.",
    )


def method_not_found() -> PaynetError:
    """``-32601`` — ``method`` is not one we implement."""
    return _err(
        -32601,
        "Метод не найден.",
        "Metod topilmadi.",
        "Method not found.",
    )


def bad_params() -> PaynetError:
    """``-32602`` — ``params`` is structurally wrong for this method."""
    return _err(
        -32602,
        "Некорректные параметры.",
        "Notoʻgʻri parametrlar.",
        "Invalid params.",
    )


def internal_error() -> PaynetError:
    """``-32603`` — an unexpected exception, still rendered at HTTP 200."""
    return _err(
        -32603,
        "Внутренняя ошибка.",
        "Ichki xato.",
        "Internal error.",
    )


def method_not_post() -> PaynetError:
    """``-32300`` — reached by a verb other than POST."""
    return _err(
        -32300,
        "Поддерживается только POST.",
        "Faqat POST qoʻllab-quvvatlanadi.",
        "Only POST is supported.",
    )


__all__ = [
    "PaynetError",
    "amount_over_limit",
    "bad_json",
    "bad_params",
    "bad_rpc_fields",
    "cancel_refused_delivered",
    "internal_error",
    "invalid_amount",
    "invalid_datetime",
    "method_not_found",
    "method_not_post",
    "order_already_paid",
    "order_not_found",
    "order_not_payable",
    "system_error",
    "transaction_not_found",
    "unknown_service",
]
