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

That same snapshot is what turns a gift line's placeholder denomination
("Любая сумма" — the one ``steam-gift`` SKU stands in for ~4200 games) into
the actual game name at display time: both ``orders.build_item_display``
and ``admin.get_refs`` call :func:`steam_gift_label` once they've confirmed
a line is on the gift SKU.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.gifts.service import (
    get_app,
    sell_price_usd,
    zone_for_country,
    zone_price_usd,
    zone_region_code,
)
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
#: Bounds the ``s.team/p/{path}`` branch the same way the other two Steam
#: link shapes are bounded — an unrestricted ``path`` accepted anything of
#: any length.
_S_TEAM_PATH_RE = re.compile(r"[A-Za-z0-9/_-]{1,64}")


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
    - ``https://s.team/p/{1-64 char path, [A-Za-z0-9/_-]}``

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
        if len(parts) == 3 and parts[1] == "p" and _S_TEAM_PATH_RE.fullmatch(parts[2]):
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
            Mutated in place and also returned: ``app_id``/``package_id``
            are normalized to ``int`` (undoing any float coercion
            ``validate_fulfillment_data`` applied), ``region`` to its
            upper-cased canonical form, and ``invite_url`` to its canonical
            form; ``app_name``, ``package_name``, ``supplier_price_usd``,
            ``zone``, and ``region_code`` are added. As of 2026-09-03
            ``region`` is a buyer-facing *country* code (``"UZ"``) — see
            :func:`yupay.modules.gifts.service.zone_for_country` — resolved
            to the *zone* we actually price from and store separately as
            ``zone``. A pre-v2 order (or a client that hasn't reloaded) can
            still send a legacy zone label (``"CIS"``) directly: when it
            isn't a known country, it's accepted as-is provided it's one of
            the offered zones. ``region_code`` is the supplier's 2-letter
            wire region — G-Engine's ``POST /gifts/orders`` wants this, not
            ``region`` or ``zone`` — resolved from the same priced entry
            ``supplier_price_usd`` came from.

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
    data["app_id"] = app_id
    package_id = _require_int(data, "package_id")
    data["package_id"] = package_id

    offered = offered_zones(settings)
    raw_region = str(data.get("region") or "").strip().upper()
    zone = zone_for_country(raw_region, offered=offered)
    if zone is None:
        # Not a country we sell — try it as a legacy zone label instead, so
        # an order created before this resolution existed (or a client that
        # hasn't reloaded) keeps pricing exactly as it did before.
        if raw_region in offered:
            zone = raw_region
        else:
            raise ValidationError("this region has no price for the selected edition")
    data["region"] = raw_region

    invite_url = parse_invite_url(str(data.get("invite_url") or ""))
    data["invite_url"] = invite_url

    try:
        app = await get_app(app_id)
    except NotFoundError as exc:
        raise ValidationError("this game is no longer available") from exc

    package = _find_package(app, package_id)
    if package is None:
        raise ValidationError("this game is no longer available")

    supplier_usd = zone_price_usd(package, zone)
    if supplier_usd is None:
        raise ValidationError("this region has no price for the selected edition")

    # Same finder as `zone_price_usd` above, so the wire region code we send
    # G-Engine always comes from the exact price entry we just billed from.
    # Normally a priced entry always carries `region`, but this is a real
    # guard, not a theoretical one: a malformed upstream entry (priced, no
    # `region` key) must 4xx here, not KeyError into a 500 on the money path.
    region_code = zone_region_code(package, zone)
    if region_code is None:
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
    # ``validate_fulfillment_data`` already rejected (422) any of these
    # keys the client tried to sneak in before this hook ever ran.
    data["app_name"] = app["name"]
    data["package_name"] = package["name"]
    data["supplier_price_usd"] = str(supplier_usd)
    data["zone"] = zone
    data["region_code"] = region_code

    return expected, data


def steam_gift_label(fulfillment_data: dict[str, Any] | None) -> str | None:
    """The customer-facing label for a priced gift line, or ``None``.

    Reads only ``app_name`` and ``package_name`` — the two display fields
    :func:`price_gift_line` snapshots onto ``fulfillment_data``. Never reads
    ``invite_url`` (the recipient's Steam profile — PII) or
    ``supplier_price_usd`` (our wholesale cost), which live in the same dict
    but must never reach a label.

    Called from the two display choke points (``orders.build_item_display``
    and ``admin.get_refs``) *after* each has already confirmed the line is
    on the gift SKU — this function only knows how to read the snapshot, not
    when it applies.

    Args:
        fulfillment_data: the order line's ``fulfillment_data`` column. Also
            accepts ``None`` for an unflushed ORM row that never had one set.

    Returns:
        ``app_name`` alone, or ``"{app_name} · {package_name}"`` when the
        edition name is present and differs from the game name — G-Engine
        usually names the base package identically to the app, so appending
        it unconditionally would print the name twice. ``None`` when
        ``app_name`` is missing or not a non-empty string, which is what an
        order placed before this snapshot existed looks like; the caller
        falls back to its own placeholder rather than crashing or rendering
        empty.
    """
    if not fulfillment_data:
        return None
    app_name = fulfillment_data.get("app_name")
    if not isinstance(app_name, str) or not app_name.strip():
        return None
    package_name = fulfillment_data.get("package_name")
    if isinstance(package_name, str) and package_name.strip() and package_name != app_name:
        return f"{app_name} · {package_name}"
    return app_name


__all__ = [
    "STEAM_GIFT_SKU_CODE",
    "is_gift_sku",
    "parse_invite_url",
    "price_gift_line",
    "steam_gift_label",
]
