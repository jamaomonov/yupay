"""FastAPI dependencies for public blog reads."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Header, Query

_SUPPORTED: frozenset[str] = frozenset({"ru", "en", "uz"})
Locale = Literal["ru", "en", "uz"]


_LOCALES: dict[str, Locale] = {"ru": "ru", "en": "en", "uz": "uz"}


def _as_locale(value: str) -> Locale:
    return _LOCALES.get(value, "ru")


def resolve_locale(
    locale: Annotated[str | None, Query(pattern="^(ru|en|uz)$")] = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> Locale:
    """Prefer ``?locale=``; otherwise the first supported ``Accept-Language`` tag.

    Defaults to ``ru``. Unlike catalogue brand pages there is no ru→uz copy
    fallback after this pick — a missing translation row is a 404.
    """
    if locale is not None:
        return _as_locale(locale)
    if not accept_language:
        return "ru"
    for tag in accept_language.split(","):
        primary = tag.split(";", 1)[0].strip().split("-", 1)[0].lower()
        if primary in _SUPPORTED:
            return _as_locale(primary)
    return "ru"


__all__ = ["resolve_locale"]
