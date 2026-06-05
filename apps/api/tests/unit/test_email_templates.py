"""Email template builders return matching subject/html/text."""

from __future__ import annotations

from yupay.modules.notifications.templates import (
    order_confirmation_email,
    order_delivered_email,
    password_reset_email,
    verify_email_email,
)


def test_verify_email_contains_link() -> None:
    t = verify_email_email(link="https://yupay.uz/ru/auth/verify?token=abc")
    assert "abc" in t.html
    assert "abc" in t.text
    assert t.subject


def test_password_reset_contains_link() -> None:
    t = password_reset_email(link="https://yupay.uz/ru/auth/reset?token=xyz")
    assert "xyz" in t.html
    assert "xyz" in t.text


def test_order_confirmation_has_order_id() -> None:
    t = order_confirmation_email(order_id="abcdef12", link="https://yupay.uz/ru/orders/abcdef12")
    assert "abcdef12" in t.html


def test_order_delivered_has_link() -> None:
    t = order_delivered_email(order_id="abcdef12", link="https://yupay.uz/ru/orders/abcdef12")
    assert "abcdef12" in t.text
