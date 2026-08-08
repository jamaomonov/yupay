"""The stuck-paid-order watchdog (ADR-0046).

Written against the incident it exists to prevent: an order paid at 13:46 whose
supplier call failed two seconds later, alerted once, and then sat undelivered
for a day because nothing asked again.
"""

from __future__ import annotations

from yupay_scheduler.jobs.stuck_orders import _format


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
