"""Locale resolution + welcome rendering for the bot.

These cover the tiny surface that the bot exposes today: read a
Telegram ``language_code`` tag, map it onto our 3 supported locales,
fall back to ``ru`` for unknown / missing values, and render the
welcome with the user's first name.
"""

from __future__ import annotations

import pytest

from yupay_bot.i18n import (
    DEFAULT_LOCALE,
    miniapp_button_label,
    resolve_locale,
    welcome_message,
)


@pytest.mark.parametrize(
    ("language_code", "expected"),
    [
        ("ru", "ru"),
        ("en", "en"),
        ("uz", "uz"),
        # Regional tags must collapse to their primary subtag.
        ("en-US", "en"),
        ("ru-RU", "ru"),
        # Case-insensitive.
        ("EN", "en"),
        # Unknown / unsupported tags fall through to the default.
        ("de", DEFAULT_LOCALE),
        ("kk", DEFAULT_LOCALE),
        # Missing / blank → default.
        (None, DEFAULT_LOCALE),
        ("", DEFAULT_LOCALE),
    ],
)
def test_resolve_locale(language_code: str | None, expected: str) -> None:
    assert resolve_locale(language_code) == expected


def test_welcome_includes_first_name() -> None:
    text = welcome_message("ru", "Жанна")
    assert "Привет, Жанна!" in text
    # Brand name should be HTML-bold for HTML parse_mode.
    assert "<b>YuPay</b>" in text


def test_welcome_falls_back_to_generic_greeting() -> None:
    text = welcome_message("en", "")
    assert "Hi, there!" in text


def test_welcome_uz_uses_latin_orthography() -> None:
    text = welcome_message("uz", "Aziz")
    # Latin-script signal: presence of the Latin "ʻ" diacritic (oʻyin).
    assert "Oʻyinlar" in text
    # No Cyrillic letters in the UZ copy.
    assert not any("Ѐ" <= ch <= "ӿ" for ch in text)


def test_button_label_per_locale() -> None:
    assert miniapp_button_label("ru") == "🚀 Открыть YuPay"
    assert miniapp_button_label("en") == "🚀 Open YuPay"
    assert miniapp_button_label("uz") == "🚀 YuPay-ni ochish"
