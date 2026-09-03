"""Live gifts-catalog proxy: Redis cache (stale-while-error) over G-Engine.

Everything here reads through :func:`_cached_json` — fresh Redis entry, then
upstream, then a stale twin on upstream failure, so a G-Engine blip or a cold
cache never turns into a 502 for a browsing customer. The pricing helpers
(:func:`sell_price_usd`, :func:`zone_price_usd`, :func:`zone_region_code`)
are pure and margin-agnostic of any request context; ``routes.py`` supplies
the margin, the offered zones, and the FX rate per request and maps raw
upstream dicts to DTOs. :func:`zone_price_usd` and :func:`zone_region_code`
both derive from the single :func:`_zone_price_entry` finder, so the price
we sell at and the wire ``region`` code we buy at always come from the same
upstream entry.

The zone stays the pricing/wire unit; the country is the buyer-facing unit.
:data:`ZONE_COUNTRIES` curates which countries each offered zone covers,
:func:`zone_for_country` resolves a buyer's chosen country back to the zone
to price from, and :func:`countries_for_zone` expands a zone into the
countries a picker should list for it.

Deliberately does not import the fulfiller (``fulfillment.suppliers.gengine``
or a wrapper around it): that would pull the whole ``fulfillment`` package
into this module's import graph, and ``orders`` imports ``gifts`` — a cycle
this module avoids by building its own transient client (:func:`_client`)
straight from settings, the same way the fulfiller does.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from redis.exceptions import RedisError

from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, UpstreamUnavailableError
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GIFT_SEARCH_MAX,
    MAX_PAGE,
    GEngineClient,
    GEngineError,
    GEngineUnavailableError,
)

log = get_logger("yupay.gifts.service")

#: Every stale twin outlives its fresh key by this much, so a cold cache plus
#: a down G-Engine still has something to serve for a full day.
_STALE_TTL_SECONDS = 86400

_LIST_TTL_SECONDS = 3600
_SEARCH_TTL_SECONDS = 900
_DETAIL_TTL_SECONDS = 900

_HOT_KEY = "gifts:hot"
_HOT_TTL_SECONDS = 3600
#: Curated app ids shown first in :func:`hot_offers`, ahead of the
#: discount scan. Empty in v1 — spec §4.2 wants this admin-editable later.
_PINNED_APP_IDS: tuple[int, ...] = ()
#: How many pages (of ``MAX_PAGE`` each) of the default listing to scan for
#: discounted apps once the pinned list is exhausted.
_HOT_SCAN_PAGES = 5
_HOT_LIMIT = 12


def _client() -> GEngineClient:
    """Build a transient G-Engine client from settings.

    Cheap to construct (see ``GEngineClient.__init__``); one instance per
    call, never held as a module-level singleton, so a settings change
    (tests included) takes effect on the next call.
    """
    s = get_settings()
    return GEngineClient(
        api_key=s.gengine_api_key,
        base_url=s.gengine_base_url,
        timeout_seconds=s.gengine_request_timeout_seconds,
    )


def sell_price_usd(supplier_usd: Decimal, margin_percent: Decimal) -> Decimal:
    """Our 2-dp sell price: supplier cost with the admin margin applied."""
    return (supplier_usd * (1 + margin_percent / 100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _zone_price_entry(package: dict[str, Any], zone: str) -> dict[str, Any] | None:
    """The ``package["prices"]`` entry for ``zone`` with a non-null price, if any.

    The single finder behind both :func:`zone_price_usd` and
    :func:`zone_region_code` — the price we sell at and the wire ``region``
    we buy at must always come from the same upstream entry, never two
    independently-matched ones. ``None`` covers both cases a caller must
    treat the same way: the zone has no entry in ``package["prices"]`` at
    all, and the zone has an entry whose ``price`` is null upstream. Either
    way there is nothing to sell.

    Skips forward past a null-price entry to a later priced one for the
    same zone — deliberate, not accidental: a zone can bucket several
    country-level entries, and this changes catalog zone-visibility for a
    duplicate-zone package so the priced entry wins over a null-price
    sibling, rather than the old first-match-wins behaviour silently
    reporting "no price" when a later entry actually had one.
    """
    entries: list[dict[str, Any]] = package.get("prices") or []
    for entry in entries:
        if entry.get("zone") != zone:
            continue
        if entry.get("price") is None:
            continue
        return entry
    return None


def zone_price_usd(package: dict[str, Any], zone: str) -> Decimal | None:
    """The wholesale USD price for ``zone`` on ``package``, or ``None``.

    ``None`` covers both cases a caller must treat the same way: the zone
    has no entry in ``package["prices"]`` at all, and the zone has an entry
    whose ``price`` is null upstream. Either way there is nothing to sell.
    """
    entry = _zone_price_entry(package, zone)
    return None if entry is None else Decimal(str(entry["price"]))


def zone_region_code(package: dict[str, Any], zone: str) -> str | None:
    """The supplier's wire ``region`` code for ``zone`` on ``package``, or ``None``.

    Our customer-facing ``zone`` (e.g. ``"CIS"``, ``"KZ"``) is not what
    G-Engine's ``POST /gifts/orders`` accepts as ``region`` — that endpoint
    wants the 2-letter country code carried on the *same* priced entry
    (``PackagePriceResponse.region``, lowercase, e.g. ``"kz"``, ``"ua"``,
    and for zone CIS it can be e.g. ``"ge"`` — verified live, and it can
    differ per package). Sending the zone label itself gets G-Engine's
    «Price not found». Derived from :func:`_zone_price_entry` so the price
    and the code come from the same entry; a malformed entry without a
    region code is refused at checkout (see :func:`zone_price_usd`, which
    may still price such an entry — the two are allowed to disagree only in
    that malformed case, which the checkout-side guard then catches).

    ``None`` when the zone has no priced entry on this package (the same
    condition under which :func:`zone_price_usd` also returns ``None``), or
    when the priced entry is missing/blank ``region`` — malformed upstream
    data, not a reason to 500 the money path.
    """
    entry = _zone_price_entry(package, zone)
    if entry is None:
        return None
    region = entry.get("region")
    return str(region) if region else None


#: Steam prices these countries as one region; G-Engine bills the zone.
#: Offered zones only, uppercase ISO-3166-1 alpha-2 country codes. KZ, RU and
#: UA each have their own zone (deliberately absent from ``CIS`` below, even
#: though Steam would otherwise bucket them there) — a country's own zone
#: always wins over CIS membership. UZ is listed first for ``CIS`` — our home
#: market, and the country :func:`countries_for_zone`/the routes layer lead
#: with when ``STEAM_GIFTS_REGION_DEFAULT`` selects that zone.
ZONE_COUNTRIES: dict[str, tuple[str, ...]] = {
    "RU": ("RU",),
    "KZ": ("KZ",),
    "UA": ("UA",),
    "CIS": ("UZ", "GE", "KG", "MD", "TJ", "TM", "AM", "AZ", "BY"),
}


def zone_for_country(country: str, *, offered: Sequence[str]) -> str | None:
    """The offered zone that sells ``country``, or ``None``.

    Reverse lookup over :data:`ZONE_COUNTRIES`, restricted to ``offered`` —
    a country belonging to a zone we don't currently sell is treated the
    same as a country we've never heard of. Case-insensitive.

    Args:
        country: an ISO-3166-1 alpha-2 code, any case.
        offered: the zones currently sold (see
            :func:`yupay.modules.gifts.settings.offered_zones`); only these
            zones' country lists are consulted.

    Returns:
        The matching zone, or ``None`` when no offered zone covers it.
    """
    code = country.strip().upper()
    if not code:
        return None
    for zone in offered:
        if code in ZONE_COUNTRIES.get(zone, ()):
            return zone
    return None


def countries_for_zone(zone: str, package: dict[str, Any]) -> tuple[str, ...]:
    """The countries ``zone`` covers, for building a country picker.

    :data:`ZONE_COUNTRIES` is the curated answer for the four zones we
    currently offer. A zone absent from that map (e.g. ``STEAM_GIFTS_REGIONS``
    widened to a zone we haven't curated yet) falls back to ``package``'s own
    priced entry for ``zone`` — its one representative country — so widening
    the offered zones never crashes or returns nothing sellable, just a
    single-country zone until the map is curated for it.

    Args:
        zone: the pricing zone (e.g. ``"CIS"``).
        package: the raw upstream package dict, consulted only for the
            fallback case.

    Returns:
        The zone's countries, uppercase, empty when unmapped and the
        package carries no priced entry for ``zone`` either.
    """
    mapped = ZONE_COUNTRIES.get(zone)
    if mapped is not None:
        return mapped
    entry = _zone_price_entry(package, zone)
    if entry is None:
        return ()
    region = entry.get("region")
    return (str(region).upper(),) if region else ()


async def _cached_json(key: str, ttl: int, fetch: Callable[[], Awaitable[Any]]) -> Any:
    """Fresh cache -> upstream -> stale-on-error. Redis being down never 500s a read.

    Return type is ``Any`` on purpose: this helper round-trips whatever
    JSON-serialisable value ``fetch`` returns (a listing-page dict, a detail
    dict, a list of hot-offer items) — each caller owns its own concrete
    shape and re-types the result.
    """
    redis = get_redis()
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
        if cached is not None:
            return json.loads(cached)
    try:
        value = await fetch()
    except (GEngineError, GEngineUnavailableError) as exc:
        with contextlib.suppress(RedisError):
            stale = await redis.get(f"{key}:stale")
            if stale is not None:
                log.warning("gifts.catalog_stale", key=key, error=str(exc))
                return json.loads(stale)
        raise UpstreamUnavailableError("the gifts catalog is temporarily unavailable") from exc
    payload = json.dumps(value)
    with contextlib.suppress(RedisError):
        await redis.set(key, payload, ex=ttl)
        await redis.set(f"{key}:stale", payload, ex=_STALE_TTL_SECONDS)
    return value


def _search_cache_key(query: str, *, offset: int, limit: int) -> str:
    """``sha1`` of the normalised query so an arbitrary search string never
    ends up embedded in a Redis key (length, punctuation, encoding).

    Truncated to ``GIFT_SEARCH_MAX`` first — the same cap
    ``GEngineClient.list_gift_apps`` applies before the query ever reaches
    G-Engine (``gengine_client.py``) — so two queries that differ only past
    that point (which upstream and the cache below both treat as identical)
    hash to the same key instead of each minting its own cache entry for a
    request that resolves identically.
    """
    truncated = query.lower().strip()[:GIFT_SEARCH_MAX]
    digest = hashlib.sha1(truncated.encode("utf-8")).hexdigest()  # noqa: S324
    return f"gifts:search:{digest}:{offset}:{limit}"


async def list_apps(
    *, search: str | None, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """One cached page of the gifts catalog: raw upstream items + total.

    A non-blank ``search`` uses the shorter-lived, hashed search cache key;
    a blank one falls back to the plain default-listing key.
    """
    query = (search or "").strip()

    async def _fetch() -> dict[str, Any]:
        items, total = await _client().list_gift_apps(
            limit=limit, offset=offset, search=query or None
        )
        return {"items": items, "total": total}

    if query:
        key = _search_cache_key(query, offset=offset, limit=limit)
        ttl = _SEARCH_TTL_SECONDS
    else:
        key = f"gifts:list:{offset}:{limit}"
        ttl = _LIST_TTL_SECONDS

    payload = await _cached_json(key, ttl, _fetch)
    return list(payload["items"]), int(payload["total"])


async def get_app(app_id: int) -> dict[str, Any]:
    """Cached full app card: packages with per-zone prices, DLC list.

    Raises :class:`NotFoundError` when G-Engine reports the app doesn't
    exist (HTTP 404) — a permanent answer, so it bypasses the stale-on-error
    fallback that ``_cached_json`` applies to a transient outage.
    """

    async def _fetch() -> dict[str, Any]:
        try:
            return await _client().get_gift_app(app_id)
        except GEngineError as exc:
            if exc.status == 404:
                raise NotFoundError(f"gift app {app_id} not found") from exc
            raise

    return dict(await _cached_json(f"gifts:detail:{app_id}", _DETAIL_TTL_SECONDS, _fetch))


async def hot_offers() -> list[dict[str, Any]]:
    """Up to 12 hot-offer items: pinned apps first, then the best discounts.

    The discount scan walks the first ``_HOT_SCAN_PAGES`` pages (500 items)
    of the *default* listing (no search term), keeps items with
    ``discount_percent > 0``, and sorts them descending. The whole result is
    cached as one unit under ``gifts:hot`` — the per-page upstream calls
    inside the scan are not cached individually.
    """

    async def _fetch() -> list[dict[str, Any]]:
        pinned: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for app_id in _PINNED_APP_IDS:
            try:
                app = await get_app(app_id)
            except NotFoundError:
                continue
            pinned.append(app)
            seen_ids.add(app_id)

        client = _client()
        discounted: list[dict[str, Any]] = []
        offset = 0
        for _ in range(_HOT_SCAN_PAGES):
            items, total = await client.list_gift_apps(limit=MAX_PAGE, offset=offset)
            for item in items:
                if item.get("id") in seen_ids:
                    continue
                discount = item.get("discount_percent") or 0
                if discount > 0:
                    discounted.append(item)
            offset += MAX_PAGE
            if offset >= total:
                break
        discounted.sort(key=lambda item: item.get("discount_percent") or 0, reverse=True)

        return (pinned + discounted)[:_HOT_LIMIT]

    return list(await _cached_json(_HOT_KEY, _HOT_TTL_SECONDS, _fetch))


__all__ = [
    "ZONE_COUNTRIES",
    "countries_for_zone",
    "get_app",
    "hot_offers",
    "list_apps",
    "sell_price_usd",
    "zone_for_country",
    "zone_price_usd",
    "zone_region_code",
]
