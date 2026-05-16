"""FastAPI dependencies used by the ``catalog`` routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, Query

_SUPPORTED_LOCALES = frozenset({"ru", "en", "uz"})
_SUPPORTED_CURRENCIES = frozenset({"USD", "RUB", "UZS", "USDT"})


def resolve_locale(
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """Pick the best supported locale from ``Accept-Language`` (or default to ``ru``).

    We deliberately ignore q-values — the storefront is always the first to be served
    in the requested locale, falling back to ru.
    """
    if not accept_language:
        return "ru"
    for tag in accept_language.split(","):
        primary = tag.split(";", 1)[0].strip().split("-", 1)[0].lower()
        if primary in _SUPPORTED_LOCALES:
            return primary
    return "ru"


def resolve_currency(
    currency: Annotated[str | None, Query(min_length=3, max_length=8)] = None,
) -> str | None:
    """Validate the optional ``currency`` query parameter.

    Returns the upper-cased code if recognised, ``None`` otherwise (so callers fall
    back to USD-only output).
    """
    if currency is None:
        return None
    cu = currency.upper()
    if cu not in _SUPPORTED_CURRENCIES:
        return None
    return cu
