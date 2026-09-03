"""Checkout hook for Steam gift order lines.

A gift line is priced entirely server-side. The client tells us which app,
package, region, and Steam invite link it wants; :func:`price_gift_line`
re-derives the price from the same 15-min-cached supplier detail the
catalog browses (:func:`yupay.modules.gifts.service.get_app`) and the
admin-editable margin, and only accepts the client's proposed
``amount_usd`` as a courtesy — within a ±2 % tolerance of a price that has
moved since the client last quoted it. The price actually billed is always
the server's own number, never the client's, even inside the tolerance
band.

``orders/service.py`` calls :func:`is_gift_sku` to decide whether a line
needs this hook, then :func:`price_gift_line` to get the authoritative
price and an enriched ``fulfillment_data`` snapshot. This module imports
nothing from ``orders``, so the reverse import there creates no cycle.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.gifts.service import get_app, sell_price_usd, zone_price_usd
from yupay.modules.gifts.settings import load_margin_percent, offered_zones

#: SKU code identifying the Steam gift product line. Defined here (not in
#: ``gifts.api``) because this is the module that actually needs it at
#: runtime, and ``gifts.api`` re-exports it from here — the other direction
#: would close an import cycle, since ``api.py`` also re-exports this
#: module's checkout functions.
STEAM_GIFT_SKU_CODE = "steam-gift"

#: How far a client-proposed ``amount_usd`` may drift from the freshly
#: computed server price before checkout refuses it outright. A supplier
#: price can move between the moment a customer opens the panel and the
#: moment they submit; a couple of percent is normal drift, not a stale
#: quote worth failing on.
_PRICE_TOLERANCE = Decimal("0.02")

_STEAM_ID64_RE = re.compile(r"\d{17}")
_STEAM_VANITY_RE = re.compile(r"[A-Za-z0-9_-]{2,32}")


def is_gift_sku(sku: object) -> bool:
    """True when ``sku`` is the single Steam-gift SKU.

    Duck-typed like ``catalog.unit_sku.is_unit_sku`` — takes ``object`` so
    it also accepts ``SimpleNamespace`` fixtures in tests, not just the
    real ``Sku`` model.
    """
    return getattr(sku, "sku_code", None) == STEAM_GIFT_SKU_CODE


def parse_invite_url(value: str) -> str:
    """Validate and canonicalize a Steam profile or friend link.

    Accepts, scheme optional and trailing slash tolerated:

    - ``https://steamcommunity.com/profiles/{17-digit steamid64}``
    - ``https://steamcommunity.com/id/{2-32 char vanity, [A-Za-z0-9_-]}``
    - ``https://s.team/p/{path}``

    A missing scheme is treated as ``https``; any other scheme (including
    plain ``http``) is rejected outright rather than silently upgraded —
    tolerating a scheme-less input is a convenience for a customer who
    pasted a bare domain, not an invitation to accept a downgrade or a
    ``javascript:`` payload. The host is matched exactly (no userinfo, no
    subdomain, no port), which also closes off tricks like
    ``steamcommunity.com@evil.com``.

    Args:
        value: the raw ``invite_url`` field from the client.

    Returns:
        The canonical ``https://...`` form, with no trailing slash.

    Raises:
        ValidationError: ``value`` is not one of the accepted shapes.
    """
    raw = (value or "").strip()
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        raise ValidationError("invite_url is not a Steam profile or friend link")

    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    if host == "steamcommunity.com":
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "profiles" and _STEAM_ID64_RE.fullmatch(parts[2]):
            return f"https://steamcommunity.com/profiles/{parts[2]}"
        if len(parts) == 3 and parts[1] == "id" and _STEAM_VANITY_RE.fullmatch(parts[2]):
            return f"https://steamcommunity.com/id/{parts[2]}"
    elif host == "s.team":
        parts = path.split("/", 2)
        if len(parts) == 3 and parts[1] == "p" and parts[2]:
            return f"https://s.team/p/{parts[2]}"

    raise ValidationError("invite_url is not a Steam profile or friend link")


def _require_int(data: dict[str, Any], key: str) -> int:
    """Return ``data[key]`` as an ``int``, or raise ``ValidationError``."""
    value = data.get(key)
    if value is None:
        raise ValidationError(f"{key} is required")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{key} is required") from exc


def _find_package(app: dict[str, Any], package_id: int) -> dict[str, Any] | None:
    """The package dict in ``app["packages"]`` matching ``package_id``, if any."""
    packages: list[dict[str, Any]] = app.get("packages") or []
    for package in packages:
        if package.get("id") == package_id:
            return package
    return None


async def price_gift_line(
    db: AsyncSession, *, line_amount_usd: Decimal | None, data: dict[str, Any]
) -> tuple[Decimal, dict[str, Any]]:
    """Re-price a Steam gift order line from the live supplier catalog.

    Never trusts the client's price: fetches the app via the 15-min-cached
    :func:`yupay.modules.gifts.service.get_app` (so checkout never hits
    upstream more than once per app per 15 min), locates the requested
    package and zone, and computes the current sell price from the
    supplier's wholesale price and the admin margin. The client's
    ``line_amount_usd`` is accepted only as a courtesy check against drift
    — within ±2 % of that computed price — and is never itself billed; the
    server's own number is, even when the client's guess was exactly
    right.

    Args:
        db: session used to read the current admin margin.
        line_amount_usd: the client's proposed unit price, or ``None``.
        data: the line's cleaned ``fulfillment_data`` — must carry
            ``app_id``, ``package_id``, ``region``, and ``invite_url``.
            Mutated in place and also returned: ``invite_url`` is rewritten
            to its canonical form and ``app_name``, ``package_name``, and
            ``supplier_price_usd`` are added.

    Returns:
        ``(expected_price_usd, enriched_data)``.

    Raises:
        ValidationError: the feature is disabled, a required field is
            missing or invalid, the app/package no longer exists upstream,
            the region has no price on this package, the amount is missing,
            or the amount has drifted more than 2 % from the current price.
        UpstreamUnavailableError: G-Engine is unreachable and no stale
            cache exists — left to propagate; a 502 during checkout is
            honest and the client can retry.
    """
    settings = get_settings()
    if not settings.steam_gifts_enabled:
        raise ValidationError("steam gifts are not available right now")

    app_id = _require_int(data, "app_id")
    package_id = _require_int(data, "package_id")

    region = str(data.get("region") or "").strip().upper()
    if region not in offered_zones(settings):
        raise ValidationError("this region is not currently offered")

    invite_url = parse_invite_url(str(data.get("invite_url") or ""))
    data["invite_url"] = invite_url

    try:
        app = await get_app(app_id)
    except NotFoundError as exc:
        raise ValidationError("this game is no longer available") from exc

    package = _find_package(app, package_id)
    if package is None:
        raise ValidationError("this game is no longer available")

    supplier_usd = zone_price_usd(package, region)
    if supplier_usd is None:
        raise ValidationError("this region has no price for the selected edition")

    expected = sell_price_usd(supplier_usd, await load_margin_percent(db))

    if line_amount_usd is None:
        raise ValidationError("amount is required for this product")
    if abs(line_amount_usd - expected) > expected * _PRICE_TOLERANCE:
        raise ValidationError(
            "the price of this gift has changed — refresh and try again",
            extra={"expected_amount_usd": str(expected)},
        )

    # Server-derived, overwriting anything client-sent — though
    # ``validate_fulfillment_data`` already stripped any of these three
    # keys the client tried to sneak in before this hook ever ran.
    data["app_name"] = app["name"]
    data["package_name"] = package["name"]
    data["supplier_price_usd"] = str(supplier_usd)

    return expected, data


__all__ = [
    "STEAM_GIFT_SKU_CODE",
    "is_gift_sku",
    "parse_invite_url",
    "price_gift_line",
]
