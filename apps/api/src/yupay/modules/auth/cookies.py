"""Refresh-token cookie helpers for the auth HTTP surface.

The refresh token is delivered as an ``HttpOnly`` cookie (ADR-0007) instead of the
JSON body, so an XSS regression cannot read a 30-day session. Attributes are
environment-aware:

- ``Secure`` and ``Domain`` are only set in production. Dev and the test suite run
  over plain ``http``/``localhost`` where a ``Secure`` cookie would be dropped by the
  browser and a ``Domain`` attribute for a bare hostname is invalid.
- ``SameSite=Lax`` + ``Path=/`` always. ``yupay.uz`` and its API/admin subdomains
  share the registrable domain, so the cookie is first-party (same-site) on the
  cross-subdomain XHR the refresh flow makes to ``api.yupay.uz``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Response

from yupay.core.config import Settings

REFRESH_COOKIE_NAME = "refresh_token"

#: The affiliate panel's own cookie.
#:
#: A separate name, not a separate mechanism. In production both cookies are
#: scoped to ``.yupay.uz``, so one name would mean a partner signing in wipes
#: their own buyer session and vice versa — and the same person can plausibly
#: be both.
PARTNER_REFRESH_COOKIE_NAME = "partner_refresh_token"


def _cookie_domain(settings: Settings) -> str | None:
    """Return the parent domain for the cookie, or ``None`` to keep it host-only.

    Host-only (dev/test/localhost) scopes the cookie to the API host, which is all
    the refresh flow needs. In production it widens to the registrable parent
    (``.yupay.uz``) derived from ``web_base_url`` so the cookie is first-party to
    every storefront/admin subdomain.
    """
    if not settings.is_prod:
        return None
    host = urlsplit(settings.web_base_url or settings.base_url).hostname
    if not host:
        return None
    labels = host.split(".")
    if len(labels) < 2:
        return None
    return "." + ".".join(labels[-2:])


def set_refresh_cookie(
    response: Response,
    *,
    token: str,
    max_age: int,
    settings: Settings,
    name: str = REFRESH_COOKIE_NAME,
) -> None:
    """Attach a rotating refresh cookie to ``response``.

    ``name`` selects which session this is — the buyer's or the affiliate
    panel's. The attributes are deliberately shared: getting ``Secure``,
    ``Domain`` and ``SameSite`` right is the part worth having one copy of.
    """
    response.set_cookie(
        key=name,
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        domain=_cookie_domain(settings),
    )


def clear_refresh_cookie(
    response: Response, *, settings: Settings, name: str = REFRESH_COOKIE_NAME
) -> None:
    """Expire a refresh cookie (logout). Attributes must match the set call."""
    response.delete_cookie(
        key=name,
        path="/",
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        domain=_cookie_domain(settings),
    )


__all__ = [
    "PARTNER_REFRESH_COOKIE_NAME",
    "REFRESH_COOKIE_NAME",
    "clear_refresh_cookie",
    "set_refresh_cookie",
]
