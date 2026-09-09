"""Rendering a money amount for a human, at the precision it was charged at.

One function, and it exists because the same two-line idiom was copied into six
alert bodies and then went wrong in all of them at once.

`f"{total:,.0f}"` was written for UZS, where whole so'm are what gets charged
and the space thousands separator earns its place. USD orders arrived with the
merchant API in M2 and nothing revisited the idiom, so on 2026-09-09 two live
Telegram alerts told the owner **«Сумма: 1 USD»** for a $0.64 order and
**«Сумма: 0 USD»** for a $0.24 one.

"0 USD" is not an imprecise number. It is a false one, on the line whose entire
job is to say that money is at stake — and it appeared on the stuck-order
watchdog, the fraud-hold alert, the antifraud group message and both auto-refund
alerts, because the idiom was duplicated rather than shared.

The precision is not a display preference: it mirrors
``orders.service._CURRENCY_QUANTUM``, which rounds a total to its currency's
smallest payable unit **before** the order is stored. Rendering has to agree
with that, or an alert prints a precision the charge never had, or hides one it
did. ``test_money_rendering_matches_the_charge_quantum`` is what keeps the two
from drifting apart.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

#: Currencies charged in whole units. Kept as a set of what *is* whole rather
#: than a map of digits, so adding a currency is one word and the default is
#: the safe one: an unknown currency renders minor units, which over-states
#: precision at worst and never hides money.
WHOLE_UNIT_CURRENCIES: Final[frozenset[str]] = frozenset({"UZS"})


def format_amount(amount: Decimal, currency: str) -> str:
    """Render ``amount`` at the precision ``currency`` is actually charged at.

    Args:
        amount: The amount, in ``currency``'s major units — an order's
            ``total_charged``, a refund, a deposit movement.
        currency: The charge currency, e.g. ``"UZS"`` or ``"USD"``. Compared
            case-insensitively.

    Returns:
        The amount with a space as the thousands separator, and two decimals
        unless the currency is charged in whole units.

    Examples:
        >>> format_amount(Decimal("250000"), "UZS")
        '250 000'
        >>> format_amount(Decimal("0.24"), "USD")
        '0.24'
    """
    digits = 0 if currency.upper() in WHOLE_UNIT_CURRENCIES else 2
    return f"{amount:,.{digits}f}".replace(",", " ")


__all__ = ["WHOLE_UNIT_CURRENCIES", "format_amount"]
