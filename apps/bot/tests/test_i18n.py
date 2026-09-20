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


def test_welcome_escapes_a_name_that_would_break_html_parsing() -> None:
    """Sentry 2026-09-19: ``Unsupported start tag "!" at byte offset 9``.

    The bot sends with ``parse_mode=HTML`` and the copy carries real ``<b>``
    tags, so Telegram parses the whole string. An unescaped ``<`` in a display
    name makes Telegram reject the ENTIRE ``sendMessage`` — the person gets no
    welcome at all, and ``/start`` is broken for them with no visible error on
    their side.
    """
    text = welcome_message("en", "<!DOCTYPE")

    assert "&lt;!DOCTYPE" in text
    # The raw sequence Telegram choked on must not survive anywhere.
    assert "<!" not in text
    # The copy's own markup is untouched — escaping the name, not the message.
    assert "<b>YuPay</b>" in text


def test_welcome_escapes_ampersands_and_tags_without_touching_quotes() -> None:
    """``&`` must be escaped too, or it can start an entity of its own.

    A quotation mark is deliberately left alone: the name lands in text, never
    in an attribute, and escaping it would print a literal ``&quot;`` to
    anyone whose display name contains one.
    """
    text = welcome_message("ru", 'Tom & "Jerry" <b>')

    assert "Tom &amp; " in text
    assert '"Jerry"' in text
    assert "&lt;b&gt;" in text


def test_a_name_of_only_markup_still_greets() -> None:
    """Escaping must not empty the name into the generic fallback by accident."""
    text = welcome_message("en", "<")

    assert "Hi, &lt;!" in text


def test_a_blank_name_still_falls_back_after_escaping() -> None:
    text = welcome_message("en", "   ")

    assert "Hi, there!" in text
