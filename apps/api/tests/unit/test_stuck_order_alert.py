"""The stuck-paid-order watchdog (ADR-0046).

Written against the incident it exists to prevent: an order paid at 13:46 whose
supplier call failed two seconds later, alerted once, and then sat undelivered
for a day because nothing asked again.

The amount tests were written against a second live failure: on 2026-09-09 two
alerts read «Сумма: 1 USD» for a $0.64 order and «Сумма: 0 USD» for a $0.24
one, because the money was formatted with ``:,.0f`` — a shape written when
every order was UZS.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay_scheduler.jobs.stuck_orders import _format, _format_amount


def test_the_message_leads_with_the_money_not_the_order_id() -> None:
    """An ops alert is read on a phone, mid-something-else.

    Whoever sees it has seconds to decide whether to stop what they are doing.
    The amount and the wait decide that; the id only matters once they have.
    """
    text = _format("019fdc77-e007-7202", "2 787 780", "UZS", 1_474, "fulfilling")

    assert "2 787 780 UZS" in text
    assert "24 ч 34 мин" in text
    # Says what to actually do — an alert that only reports a fact gets deferred.
    assert "Fulfilment Inbox" in text
    assert "вернуть деньги" in text


def test_short_waits_read_in_minutes() -> None:
    text = _format("abc12345", "14 246", "UZS", 17, "paid")
    assert "17 мин" in text
    assert " ч " not in text


def test_order_id_is_truncated_and_escaped() -> None:
    # Ids are safe by construction, but the formatter splices into parse_mode
    # HTML and must not become the one place that trusts its input.
    text = _format("<b>pwn</b>-1234", "1", "UZS", 1, "paid")
    assert "<b>pwn" not in text.replace("<b>🚨", "")
    assert "&lt;b&gt;pwn" in text


@pytest.mark.parametrize(
    ("charged", "expected"),
    [
        (Decimal("0.240000"), "0.24"),  # the live alert that read "0"
        (Decimal("0.640000"), "0.64"),  # the live alert that read "1"
        (Decimal("1.500000"), "1.50"),  # would have read "2"
        (Decimal("12.000000"), "12.00"),
        (Decimal("1234.560000"), "1 234.56"),
    ],
)
def test_usd_keeps_its_cents(charged: Decimal, expected: str) -> None:
    """«0 USD» is not an imprecise number, it is a false one."""
    assert _format_amount(charged, "USD") == expected


@pytest.mark.parametrize(
    ("charged", "expected"),
    [
        (Decimal("900.000000"), "900"),
        (Decimal("45000.000000"), "45 000"),
        (Decimal("2787780.000000"), "2 787 780"),
    ],
)
def test_uzs_stays_whole_with_a_space_separator(charged: Decimal, expected: str) -> None:
    """UZS is charged in whole so'm, so decimals here would be invented.

    This is the test that fails if a later fix reaches for two decimals
    everywhere: the alert would then print a precision the charge never had.
    """
    rendered = _format_amount(charged, "UZS")
    assert rendered == expected
    assert "." not in rendered, "UZS grew decimals it was never charged at"
    assert "," not in rendered, "the thousands separator must stay a space"


def test_a_currency_we_have_not_met_yet_gets_minor_units() -> None:
    """Everything except UZS is stored quantized to 0.01 (`_CURRENCY_QUANTUM`)."""
    assert _format_amount(Decimal("0.240000"), "USDT") == "0.24"
    assert _format_amount(Decimal("99.900000"), "RUB") == "99.90"


def test_the_amount_reaches_the_alert_body() -> None:
    assert "Сумма: <b>0.24 USD</b>" in _format("abc12345", "0.24", "USD", 75, "fulfilling")
