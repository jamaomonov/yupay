"""Public HTTP routes for the ``gifts`` module: catalog browsing.

Every route here is guarded by :func:`_ensure_enabled`, a router-level
dependency, so the whole surface 404s while ``steam_gifts_enabled`` is off —
a new route added later inherits the guard automatically. No per-route rate
limit bucket: same posture as ``catalog/routes.py``, which relies on the
app-wide slowapi defaults.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.service import FxService, FxUnavailableError
from yupay.modules.gifts.schemas import (
    GiftAppDetailOut,
    GiftAppOut,
    GiftPackageOut,
    GiftRegionOut,
    GiftsListOut,
    GiftZonePriceOut,
)
from yupay.modules.gifts.service import (
    countries_for_zone,
    get_app,
    hot_offers,
    list_apps,
    sell_price_usd,
    zone_for_country,
    zone_price_usd,
)
from yupay.modules.gifts.settings import default_zone, load_margin_percent, offered_zones


def _ensure_enabled() -> None:
    """404 every route under this router while the feature flag is off."""
    if not get_settings().steam_gifts_enabled:
        raise NotFoundError("steam gifts catalog is not enabled")


router = APIRouter(prefix="/gifts", tags=["gifts"], dependencies=[Depends(_ensure_enabled)])


async def _uzs_rate(fx: FxService) -> Decimal | None:
    """USD->UZS rate for this request, or ``None`` on an FX outage.

    Fetched once per request; callers multiply this rate per row rather
    than calling ``fx.convert`` again for every item.
    """
    try:
        result = await fx.convert(Decimal("1"), base="USD", quote="UZS")
    except FxUnavailableError:
        return None
    return result.rate


def _to_uzs(usd: Decimal | None, rate: Decimal | None) -> str | None:
    """Whole-UZS display string, or ``None`` when either input is missing."""
    if usd is None or rate is None:
        return None
    return str((usd * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _count(item: dict[str, Any], full_key: str, ids_key: str) -> int:
    """Prefer the length of a full list (``packages``/``dlc``, present on a
    detail payload) over the length of its id-only twin (``package_ids``/
    ``dlc_ids``, present on a listing item) — both shapes reach this via
    :func:`_app_out`."""
    full = item.get(full_key)
    if full is not None:
        return len(full)
    return len(item.get(ids_key) or [])


def _app_out(item: dict[str, Any], *, margin: Decimal, rate: Decimal | None) -> GiftAppOut:
    """Map one raw upstream item to :class:`GiftAppOut`.

    ``price_usd``/``price_uzs`` here are the *default-zone display* price,
    derived from the item's flat reference ``price`` field — listing items,
    DLC entries, and a detail payload's top level all carry that one field,
    never a per-zone breakdown (that only exists on ``packages[]``).
    """
    supplier_price = item.get("price")
    price_usd = (
        sell_price_usd(Decimal(str(supplier_price)), margin) if supplier_price is not None else None
    )
    return GiftAppOut(
        app_id=int(item["id"]),
        name=str(item.get("name") or ""),
        image=item.get("image"),
        type=str(item.get("type") or ""),
        price_usd=str(price_usd) if price_usd is not None else None,
        price_uzs=_to_uzs(price_usd, rate),
        discount_percent=item.get("discount_percent"),
        packages_count=_count(item, "packages", "package_ids"),
        dlc_count=_count(item, "dlc", "dlc_ids"),
    )


def _package_out(
    package: dict[str, Any], *, margin: Decimal, zones: list[str], rate: Decimal | None
) -> GiftPackageOut:
    """One package priced across every offered zone that has a wholesale
    price — never the raw wholesale figure, always our sell price."""
    prices: list[GiftZonePriceOut] = []
    for zone in zones:
        wholesale = zone_price_usd(package, zone)
        if wholesale is None:
            continue
        sell = sell_price_usd(wholesale, margin)
        prices.append(
            GiftZonePriceOut(zone=zone, price_usd=str(sell), price_uzs=_to_uzs(sell, rate))
        )
    return GiftPackageOut(
        id=int(package["id"]),
        name=str(package.get("name") or ""),
        image=package.get("image"),
        discount_percent=package.get("discount_percent"),
        prices=prices,
    )


def _regions_out(
    raw_packages: list[dict[str, Any]],
    packages_out: list[GiftPackageOut],
    *,
    zones: list[str],
    default_country: str,
) -> list[GiftRegionOut]:
    """One row per country covered by an offered, priced zone.

    Reuses ``packages_out`` — already margin- and fx-applied by
    :func:`_package_out` — rather than recomputing a price, so this is
    purely an expansion/ordering step, never a second source of the sell
    price. For each offered zone, the *first* package (catalog order) that
    prices it wins — the same "priced on at least one package" rule
    :func:`get_catalog_app` already applies to the deprecated ``zones``
    field. Order: ``default_country`` first, then the rest of its zone's
    countries, then the remaining zones in ``STEAM_GIFTS_REGIONS`` order —
    a package switch later re-prices from ``GiftPackageOut.prices``
    directly, this list is only the initial country picker.
    """
    default_zone_code = zone_for_country(default_country, offered=zones)
    ordered_zones: list[str] = [default_zone_code] if default_zone_code else []
    for zone in zones:
        if zone not in ordered_zones:
            ordered_zones.append(zone)

    zone_price: dict[str, GiftZonePriceOut] = {}
    zone_raw_package: dict[str, dict[str, Any]] = {}
    for raw_package, package_out in zip(raw_packages, packages_out, strict=True):
        for zone_price_entry in package_out.prices:
            if zone_price_entry.zone not in zone_price:
                zone_price[zone_price_entry.zone] = zone_price_entry
                zone_raw_package[zone_price_entry.zone] = raw_package

    regions: list[GiftRegionOut] = []
    for zone in ordered_zones:
        price = zone_price.get(zone)
        if price is None:
            continue
        countries = countries_for_zone(zone, zone_raw_package[zone])
        if zone == default_zone_code and default_country in countries:
            countries = (default_country, *(c for c in countries if c != default_country))
        for country in countries:
            regions.append(
                GiftRegionOut(
                    country=country,
                    zone=zone,
                    price_usd=price.price_usd,
                    price_uzs=price.price_uzs,
                )
            )
    return regions


@router.get(
    "/catalog",
    response_model=GiftsListOut,
    summary="Steam gifts catalog listing",
)
async def get_catalog(
    db: Annotated[AsyncSession, Depends(db_session)],
    search: str | None = None,
    # Bounded the same way as reviews/routes.py:82 — every distinct
    # (search, limit, offset) triple mints its own ``gifts:list``/
    # ``gifts:search`` Redis key plus a 24h stale twin (see
    # ``gifts/service.py::_cached_json``), and an unbounded ``limit`` is an
    # unbounded number of those keys for one upstream call each.
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> GiftsListOut:
    """Paged catalog listing, our sell price applied per row."""
    margin = await load_margin_percent(db)
    fx = build_default_service()
    rate = await _uzs_rate(fx)
    items, total = await list_apps(search=search, limit=limit, offset=offset)
    return GiftsListOut(
        items=[_app_out(item, margin=margin, rate=rate) for item in items], total=total
    )


@router.get(
    "/catalog/hot",
    response_model=GiftsListOut,
    summary="Curated hot offers (pinned + best current discounts)",
)
async def get_hot(
    db: Annotated[AsyncSession, Depends(db_session)],
) -> GiftsListOut:
    """Up to 12 hot-offer rows, priced the same way as the listing."""
    margin = await load_margin_percent(db)
    fx = build_default_service()
    rate = await _uzs_rate(fx)
    items = await hot_offers()
    apps = [_app_out(item, margin=margin, rate=rate) for item in items]
    return GiftsListOut(items=apps, total=len(apps))


@router.get(
    "/catalog/{app_id}",
    response_model=GiftAppDetailOut,
    summary="Gift app detail: packages priced per offered zone",
)
async def get_catalog_app(
    app_id: int,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> GiftAppDetailOut:
    """Full app card. ``regions`` is the country picker (``region_default``
    first), each entry priced from its zone. ``zones``/``zone_default`` are
    the deprecated zone-label twins, narrowed to the offered zones that
    actually have a price on at least one package."""
    settings = get_settings()
    margin = await load_margin_percent(db)
    zones = offered_zones(settings)
    fx = build_default_service()
    rate = await _uzs_rate(fx)

    detail = await get_app(app_id)
    base = _app_out(detail, margin=margin, rate=rate)
    raw_packages = list(detail.get("packages") or [])
    packages = [_package_out(pkg, margin=margin, zones=zones, rate=rate) for pkg in raw_packages]
    priced_zones = {price.zone for pkg in packages for price in pkg.prices}
    zones_out = [z for z in zones if z in priced_zones]
    default_country = default_zone(settings)

    return GiftAppDetailOut(
        **base.model_dump(),
        description=detail.get("description"),
        packages=packages,
        dlc_total=len(detail.get("dlc") or []),
        zones=zones_out,
        zone_default=default_country,
        regions=_regions_out(raw_packages, packages, zones=zones, default_country=default_country),
        region_default=default_country,
    )


@router.get(
    "/catalog/{app_id}/dlc",
    response_model=GiftsListOut,
    summary="An app's DLC list, filtered and paged server-side",
)
async def get_catalog_app_dlc(
    app_id: int,
    db: Annotated[AsyncSession, Depends(db_session)],
    search: str | None = None,
    limit: int = 24,
    offset: int = 0,
) -> GiftsListOut:
    """Filter/slice the cached detail's ``dlc[]`` in-process.

    Never the flat catalog listing — a DLC id does not resolve through
    ``GET /gifts/catalog``, only through its parent app's detail payload.
    """
    margin = await load_margin_percent(db)
    fx = build_default_service()
    rate = await _uzs_rate(fx)

    detail = await get_app(app_id)
    dlc_items = list(detail.get("dlc") or [])
    if search:
        needle = search.strip().lower()
        dlc_items = [d for d in dlc_items if needle in str(d.get("name") or "").lower()]
    total = len(dlc_items)
    page = dlc_items[offset : offset + limit]
    items = [_app_out(item, margin=margin, rate=rate) for item in page]
    return GiftsListOut(items=items, total=total)


__all__ = ["router"]
