"""Public ``/skins/*`` reads. Every one 404s while ``cs2_skins_enabled`` is off.

No per-route rate bucket here: these read only our own database, the same
posture as ``catalog/routes.py``. The listings proxy (``listings.py``) is
the exception and carries its own bucket.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError
from yupay.core.redis import get_redis
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerClient
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.service import FxService, FxUnavailableError
from yupay.modules.skins.images import steam_image
from yupay.modules.skins.listings import listings_for
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.pricing import PricingRules, quote, to_uzs
from yupay.modules.skins.schemas import (
    FacetOut,
    RarityFacetOut,
    SkinDetailOut,
    SkinFacetsOut,
    SkinFamilyMemberOut,
    SkinItemOut,
    SkinListingOut,
    SkinListingsOut,
    SkinListingSummaryOut,
    SkinsPageOut,
    SkinStickerOut,
    SkinSuggestOut,
)
from yupay.modules.skins.service import (
    CatalogQuery,
    Sort,
    catalog_version,
    facets,
    family,
    get_item,
    list_items,
    suggest,
)
from yupay.modules.skins.settings import enabled_categories, load_rules

_PAGE_TTL = 60


def _ensure_enabled() -> None:
    """404 every route under this router while the feature flag is off."""
    if not get_settings().cs2_skins_enabled:
        raise NotFoundError("cs2 skins catalog is not enabled")


router = APIRouter(prefix="/skins", tags=["skins"], dependencies=[Depends(_ensure_enabled)])


def _fx() -> FxService:
    return build_default_service()


async def _uzs_rate(fx: FxService) -> Decimal | None:
    try:
        return (await fx.convert(Decimal("1"), base="USD", quote="UZS")).rate
    except FxUnavailableError:
        return None


def _to_uzs(usd: Decimal | None, rate: Decimal | None, rules: PricingRules) -> str | None:
    if usd is None or rate is None:
        return None
    return str(to_uzs(usd, rate, round_to=rules.uzs_round_to))


def _units_to_usd(units: int | None) -> str | None:
    return None if units is None else str(Decimal(units) / Decimal(1000))


def _item_out(item: SkinItem, rules: PricingRules, rate: Decimal | None) -> SkinItemOut:
    # Stored by ``repricing.reprice_rows`` from the same ``quote()``: the card
    # shows the number every filter and sort reads.
    price = item.sell_price_usd
    discount = (
        item.discount_percent if item.discount_percent and item.discount_percent > 0 else None
    )
    return SkinItemOut(
        slug=item.slug,
        name=item.market_hash_name,
        phase=item.phase or None,
        category=item.category,
        weapon=item.weapon,
        skin=item.skin,
        exterior=item.exterior,
        stattrak=item.stattrak,
        souvenir=item.souvenir,
        rarity=item.rarity,
        rarity_color=item.rarity_color,
        image_url=steam_image(item.image_url, host=get_settings().cs2_skins_image_host),
        price_usd=None if price is None else str(price),
        price_uzs=_to_uzs(price, rate, rules),
        steam_price_usd=_units_to_usd(item.steam_price_units),
        discount_percent=discount,
        count=item.count_auto,
        min_float=None if item.min_float is None else str(item.min_float),
        max_float=None if item.max_float is None else str(item.max_float),
    )


async def _cached(key_parts: dict[str, Any], build: Any) -> Any:
    """60 s Redis cache keyed by the catalogue version and a digest of the query."""
    redis = get_redis()
    version = await catalog_version(redis)
    # A cache key, not a secret: sha1 keeps arbitrary query text out of Redis keys.
    digest = hashlib.sha1(json.dumps(key_parts, sort_keys=True, default=str).encode()).hexdigest()  # noqa: S324
    key = f"skins:{key_parts['kind']}:{version}:{digest}"
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
        if cached is not None:
            return json.loads(cached)
    value = await build()
    with contextlib.suppress(RedisError):
        await redis.set(key, json.dumps(value), ex=_PAGE_TTL)
    return value


@router.get("/catalog", response_model=SkinsPageOut, summary="Browse the skins catalogue")
async def get_catalog(
    db: Annotated[AsyncSession, Depends(db_session)],
    category: str | None = None,
    weapon: str | None = None,
    exterior: str | None = None,
    stattrak: bool | None = None,
    souvenir: bool | None = None,
    rarity: Annotated[str | None, Query(max_length=64)] = None,
    min_uzs: Annotated[Decimal | None, Query(ge=0, le=10**12)] = None,
    max_uzs: Annotated[Decimal | None, Query(ge=0, le=10**12)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    sort: Sort = "price",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
) -> SkinsPageOut:
    rate = await _uzs_rate(_fx())
    # Bounds arrive in soʻm (what the customer typed) and compare with our
    # USD sell price. Without a rate the bounds are dropped, not guessed.
    min_usd = None if min_uzs is None or rate is None else min_uzs / rate
    max_usd = None if max_uzs is None or rate is None else max_uzs / rate
    query = CatalogQuery(
        category=category,
        weapon=weapon,
        exterior=exterior,
        stattrak=stattrak,
        souvenir=souvenir,
        rarity=rarity,
        min_usd=min_usd,
        max_usd=max_usd,
        q=q,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )
    categories = enabled_categories(get_settings())

    async def build() -> dict[str, Any]:
        rules = await load_rules(db)
        items, next_cursor = await list_items(db, query, categories=categories)
        return SkinsPageOut(
            items=[_item_out(i, rules, rate) for i in items], next_cursor=next_cursor
        ).model_dump(mode="json")

    return SkinsPageOut.model_validate(await _cached({"kind": "catalog", **query.__dict__}, build))


@router.get("/facets", response_model=SkinFacetsOut, summary="Counts per category, weapon, wear")
async def get_facets(
    db: Annotated[AsyncSession, Depends(db_session)],
    category: Annotated[str | None, Query(max_length=32)] = None,
) -> SkinFacetsOut:
    """Facet counts; with ``category`` the weapon, wear and rarity facets are scoped to it."""
    categories = enabled_categories(get_settings())

    async def build() -> dict[str, Any]:
        f = await facets(db, categories=categories, category=category)
        return SkinFacetsOut(
            categories=[FacetOut(value=v, count=c) for v, c in f.categories],
            weapons=[FacetOut(value=v, count=c) for v, c in f.weapons],
            exteriors=[FacetOut(value=v, count=c) for v, c in f.exteriors],
            rarities=[RarityFacetOut(value=v, count=c, color=k) for v, c, k in f.rarities],
        ).model_dump(mode="json")

    return SkinFacetsOut.model_validate(
        await _cached({"kind": "facets", "category": category}, build)
    )


@router.get("/suggest", response_model=SkinSuggestOut, summary="Search-as-you-type")
async def get_suggest(
    db: Annotated[AsyncSession, Depends(db_session)],
    q: Annotated[str, Query(min_length=1, max_length=80)],
) -> SkinSuggestOut:
    categories = enabled_categories(get_settings())

    async def build() -> dict[str, Any]:
        rules = await load_rules(db)
        rate = await _uzs_rate(_fx())
        items = await suggest(db, q, categories=categories)
        return SkinSuggestOut(items=[_item_out(i, rules, rate) for i in items]).model_dump(
            mode="json"
        )

    return SkinSuggestOut.model_validate(await _cached({"kind": "suggest", "q": q.lower()}, build))


@router.get("/{slug}", response_model=SkinDetailOut, summary="One item with its cheapest listings")
async def get_detail(slug: str, db: Annotated[AsyncSession, Depends(db_session)]) -> SkinDetailOut:
    item = await get_item(db, slug, categories=enabled_categories(get_settings()))
    rules = await load_rules(db)
    rate = await _uzs_rate(_fx())
    base = _item_out(item, rules, rate)
    cheapest = []
    for entry in item.cheapest_auto:
        usd = quote(
            int(entry["price_units"]),
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.count_auto,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd
        cheapest.append(
            SkinListingSummaryOut(
                listing_id=int(entry["listing_id"]),
                price_usd=str(usd),
                price_uzs=_to_uzs(usd, rate, rules),
            )
        )
    members = [
        SkinFamilyMemberOut(
            slug=m.slug,
            exterior=m.exterior,
            stattrak=m.stattrak,
            souvenir=m.souvenir,
            price_usd=None if m.sell_price_usd is None else str(m.sell_price_usd),
            price_uzs=_to_uzs(m.sell_price_usd, rate, rules),
            count=m.count_auto,
        )
        for m in await family(db, item, categories=enabled_categories(get_settings()))
    ]
    return SkinDetailOut(**base.model_dump(), cheapest=cheapest, family=members)


@router.get(
    "/{slug}/listings",
    response_model=SkinListingsOut,
    summary="Live auto listings for one item (cached, rate-budgeted, degradable)",
)
async def get_listings(
    slug: str, request: Request, db: Annotated[AsyncSession, Depends(db_session)]
) -> SkinListingsOut:
    # Spends supplier quota on a cache miss — the bucket bounds distinct items per address.
    await guard_ip(request, bucket="skins-listings")
    settings = get_settings()
    item = await get_item(db, slug, categories=enabled_categories(settings))
    rules = await load_rules(db)
    rate = await _uzs_rate(_fx())
    client = WaxpeerClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.cs2_skins_listings_timeout_seconds,
    )
    rows, degraded = await listings_for(
        item,
        client=client,
        redis=get_redis(),
        budget_per_minute=settings.cs2_skins_listings_bucket_per_minute
        if settings.waxpeer_api_key
        else 0,
    )
    items = []
    for row in rows:
        usd = quote(
            row.price_units,
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.count_auto,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd
        items.append(
            SkinListingOut(
                listing_id=row.listing_id,
                price_usd=str(usd),
                price_uzs=_to_uzs(usd, rate, rules),
                float_value=row.float_value,
                paint_seed=row.paint_seed,
                stickers=[
                    SkinStickerOut.model_validate(
                        {
                            **s,
                            "image": steam_image(
                                s.get("image"), host=settings.cs2_skins_image_host
                            ),
                        }
                    )
                    for s in row.stickers
                ],
                inspect_url=row.inspect_url,
            )
        )
    return SkinListingsOut(items=items, degraded=degraded)


__all__ = ["router"]
