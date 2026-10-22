"""What a push says, in the buyer's language. Short: a lock screen shows two lines."""

from __future__ import annotations

from decimal import Decimal
from typing import Final

#: Push kinds, one per order outcome the buyer is waiting for.
ORDER_DELIVERED: Final = "order_delivered"
ORDER_FAILED: Final = "order_failed"
ORDER_REFUNDED: Final = "order_refunded"
WALLET_CREDITED: Final = "wallet_credited"

_TEXT: Final[dict[str, dict[str, tuple[str, str]]]] = {
    ORDER_DELIVERED: {
        "ru": ("Заказ выполнен", "{what}"),
        "en": ("Order completed", "{what}"),
        "uz": ("Buyurtma bajarildi", "{what}"),
    },
    ORDER_FAILED: {
        "ru": ("Заказ не выполнен", "{what}. Напишите в поддержку, поможем"),
        "en": ("Order not completed", "{what}. Message support and we'll help"),
        "uz": ("Buyurtma bajarilmadi", "{what}. Qoʻllab-quvvatlashga yozing, yordam beramiz"),
    },
    ORDER_REFUNDED: {
        "ru": ("Деньги возвращены", "{what}"),
        "en": ("Money returned", "{what}"),
        "uz": ("Pul qaytarildi", "{what}"),
    },
    WALLET_CREDITED: {
        "ru": ("Баланс пополнен", "+{amount} сум"),
        "en": ("Balance topped up", "+{amount} soʻm"),
        "uz": ("Balans toʻldirildi", "+{amount} soʻm"),
    },
}

_ORDER: Final = {"ru": "Заказ {id}", "en": "Order {id}", "uz": "Buyurtma {id}"}


def _locale(locale: str | None) -> str:
    return locale if locale in ("ru", "en", "uz") else "ru"


def what(*, brand: str | None, extra_lines: int, order_id: str, locale: str | None) -> str:
    """The order as a lock screen can name it: ``PUBG Mobile`` or ``PUBG Mobile +1``."""
    if not brand:
        return _ORDER[_locale(locale)].format(id=order_id[:8])
    return f"{brand} +{extra_lines}" if extra_lines > 0 else brand


def amount(value: Decimal) -> str:
    """Whole soʻm grouped by thin spaces: ``50 000``."""
    return f"{int(value):,}".replace(",", " ")


def render(kind: str, locale: str | None, **values: str) -> tuple[str, str]:
    """``(title, body)`` for ``kind``; the body is cut to what the queue column holds."""
    title, body = _TEXT[kind][_locale(locale)]
    return title, body.format(**values)[:240]
