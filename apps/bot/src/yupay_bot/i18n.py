"""Locale resolution + message catalogue for the YuPay bot.

The catalogue is intentionally inline (not loaded from JSON) so the
typechecker / IDE catches missing keys when we add a new copy block.
For the storefront's mini-app catalogue we use ``next-intl``; the
bot's surface is small enough that 3 dicts here are simpler than a
second i18n stack.
"""

from __future__ import annotations

from html import escape
from typing import Literal

Locale = Literal["ru", "en", "uz"]
DEFAULT_LOCALE: Locale = "ru"


def resolve_locale(language_code: str | None) -> Locale:
    """Map Telegram's ``User.language_code`` to one of our supported locales.

    Telegram returns an IETF tag from the user's Telegram language
    setting (``"en"``, ``"ru"``, ``"uz"``, sometimes regional like
    ``"en-US"``). We match on the primary subtag.

    Falls back to :data:`DEFAULT_LOCALE` (``ru``) for unknown / missing
    values — the bot's primary market is UZ, where the vast majority
    of Telegram users picked ``ru`` years before ``uz`` localisation
    existed, so a Russian fallback reads naturally to almost everyone.
    """
    if not language_code:
        return DEFAULT_LOCALE
    primary = language_code.split("-", 1)[0].lower()
    if primary in ("ru", "en", "uz"):
        return primary  # type: ignore[return-value]
    return DEFAULT_LOCALE


# ---------- copy ----------


def welcome_message(locale: Locale, first_name: str) -> str:
    """Welcome text the bot sends in response to ``/start``.

    **The name is HTML-escaped, and that is not defensive tidiness.** The bot
    sends with ``parse_mode=HTML`` (``DefaultBotProperties`` in ``main``) and
    the copy below carries real ``<b>`` tags, so Telegram parses the whole
    string. ``first_name`` is whatever the user typed into their Telegram
    profile, and a ``<`` in it makes Telegram reject the **entire**
    ``sendMessage`` with ``can't parse entities`` — the person gets no welcome
    at all and ``/start`` is simply broken for them, silently, forever.

    That is not hypothetical: Sentry, 2026-09-19 11:08 UTC —
    ``Unsupported start tag "!" at byte offset 9``, raised from ``on_start``
    for a display name containing ``<!``.

    ``quote=False`` because the name lands in text, never in an attribute:
    escaping ``"`` there would put a visible ``&quot;`` in front of anyone
    whose name contains a quotation mark.

    Args:
        locale: Which copy block to use.
        first_name: The user's Telegram display name, unescaped and
            untrusted.

    Returns:
        HTML-safe message text.
    """
    safe_name = escape(first_name.strip(), quote=False) or _GENERIC_GREETING[locale]
    return _WELCOME[locale].format(name=safe_name)


def miniapp_button_label(locale: Locale) -> str:
    """Text on the inline ``WebAppInfo`` button under the welcome."""
    return _BUTTONS[locale]


_GENERIC_GREETING: dict[Locale, str] = {
    "ru": "друг",
    "en": "there",
    "uz": "doʻst",
}

_WELCOME: dict[Locale, str] = {
    "ru": (
        "Привет, {name}! 👋\n\n"
        "<b>YuPay</b> — пополнение игр и сервисов прямо в Telegram.\n\n"
        "🎮 Игры — PUBG Mobile, Standoff 2 и другие\n"
        "🎁 Подарочные карты — Steam и не только\n"
        "💳 Оплата — Click, Payme, Uzum, СБП, USDT\n\n"
        "Нажмите кнопку ниже, чтобы открыть мини-приложение."
    ),
    "en": (
        "Hi, {name}! 👋\n\n"
        "<b>YuPay</b> lets you top up games and services right inside Telegram.\n\n"
        "🎮 Games — PUBG Mobile, Standoff 2 and more\n"
        "🎁 Gift cards — Steam and others\n"
        "💳 Payment — Click, Payme, Uzum, SBP, USDT\n\n"
        "Tap the button below to open the mini app."
    ),
    "uz": (
        "Salom, {name}! 👋\n\n"
        "<b>YuPay</b> orqali Telegram ichida oʻyinlar va xizmatlarni toʻldiring.\n\n"
        "🎮 Oʻyinlar — PUBG Mobile, Standoff 2 va boshqalar\n"
        "🎁 Sovgʻa kartalar — Steam va boshqalar\n"
        "💳 Toʻlov — Click, Payme, Uzum, SBP, USDT\n\n"
        "Mini-ilovani ochish uchun pastdagi tugmani bosing."
    ),
}

_BUTTONS: dict[Locale, str] = {
    "ru": "🚀 Открыть YuPay",
    "en": "🚀 Open YuPay",
    "uz": "🚀 YuPay-ni ochish",
}


__all__ = [
    "DEFAULT_LOCALE",
    "Locale",
    "miniapp_button_label",
    "resolve_locale",
    "welcome_message",
]
