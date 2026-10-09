"""Live offers of one item from csmarket (ADR-0098) — the csmarket twin of ``listings``.

Order of attempts: fresh Redis → (breaker closed and budget left) ``GET /catalog/{id}/offers``
→ stale Redis → nothing, ``degraded``. The feed names no individual offers, so there is no
snapshot fallback; an empty degraded answer makes the page show "try again", never a 500.

Same carve-out as the Waxpeer read (AGENTS.md §10): a catalogue read off the order path,
short timeout, Redis-cached, a 2-minute breaker and a process-wide per-minute budget under the
key's read limit.

The storefront speaks a numeric ``listing_id``; csmarket's ``offer_id`` is an opaque string.
:func:`listing_id_for` maps one to the other with a stable 52-bit hash, which a JavaScript
number holds exactly, and the offer keeps its real id in ``Listing.offer_id``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Awaitable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.csmarket_client import (
    CsmarketError,
    CsmarketRateLimitedError,
    CsmarketUnavailableError,
    Offer,
)
from yupay.modules.skins.listings import Listing
from yupay.modules.skins.models import SkinItem

log = get_logger("yupay.skins.listings_csmarket")

#: Short: the lots that sell fastest are the cheapest, which are the ones shown first. csmarket
#: caches its list for 60 s itself, so this mostly bounds how long *we* keep a lot we were
#: told is gone (see :func:`forget`) — and a sold lot is evicted at once anyway.
FRESH_TTL = 30
STALE_TTL = 3600
BREAKER_TTL = 120
_BUDGET_TTL = 120
_BREAKER_KEY = "skins:csm:breaker"


class OfferClient(Protocol):
    """What this module needs from csmarket (``CsmarketClient`` satisfies it)."""

    @property
    def configured(self) -> bool: ...

    async def offers(self, item_id: str, *, timeout: float | None = None) -> list[Offer]: ...


def listing_id_for(offer_id: str) -> int:
    """A stable positive 52-bit integer for an offer id (below 2**53, exact in JS)."""
    return int(hashlib.sha256(offer_id.encode()).hexdigest()[:13], 16)


def to_listing(offer: Offer) -> Listing:
    """An offer as the storefront's listing; ``price_units`` is our cost on the key's tariff."""
    return Listing(
        listing_id=listing_id_for(offer.offer_id),
        price_units=offer.price_units,
        float_value=offer.float_value,
        paint_seed=offer.paint_seed,
        stickers=offer.stickers,
        inspect_url=None,
        delivery=offer.delivery,
        offer_id=offer.offer_id,
    )


def cache_key(slug: str) -> str:
    """Redis key of one item's cached csmarket offers (the stale twin adds ``:stale``)."""
    return f"skins:listings:csm:{slug}"


#: How long a lot reported sold stays hidden from the list. csmarket's own list is cached for
#: 60 s and a LIS-SKINS lot can linger in it until the next five-minute export.
GONE_TTL = 360


def _gone_key(slug: str) -> str:
    return f"skins:csm:gone:{slug}"


async def forget(redis: Redis, slug: str, offer_id: str | None = None) -> None:
    """Drop an item's cached offers after a lot turned out sold, and hide that lot.

    Without it the page keeps offering the sold lot — from our cache, and again from
    csmarket's own list until it catches up — and the buyer walks into the same refusal.
    """
    with contextlib.suppress(RedisError):
        await redis.delete(cache_key(slug), f"{cache_key(slug)}:stale")
        if offer_id:
            # redis-py types set commands as "awaitable or value"; on the asyncio client
            # they are always awaitable.
            await cast("Awaitable[int]", redis.sadd(_gone_key(slug), offer_id))
            await redis.expire(_gone_key(slug), GONE_TTL)


async def _without_gone(redis: Redis, slug: str, rows: list[Listing]) -> list[Listing]:
    gone: set[str] = set()
    with contextlib.suppress(RedisError):
        members = await cast("Awaitable[set[Any]]", redis.smembers(_gone_key(slug)))
        gone = {str(x) for x in members}
    return [r for r in rows if r.offer_id not in gone] if gone else rows


async def _budget_ok(redis: Redis, limit: int) -> bool:
    if limit <= 0:
        return False
    key = f"skins:csm:budget:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    with contextlib.suppress(RedisError):
        used = await redis.incr(key)
        await redis.expire(key, _BUDGET_TTL)
        return int(used) <= limit
    return True


async def csmarket_listings_for(
    item: SkinItem,
    *,
    client: OfferClient,
    redis: Redis,
    budget_per_minute: int,
    timeout_seconds: float,
) -> tuple[list[Listing], bool]:
    """``(listings, degraded)`` for one item, cheapest first."""
    key = cache_key(item.slug)
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
        if cached is not None:
            return await _without_gone(
                redis, item.slug, [Listing(**e) for e in json.loads(cached)]
            ), False

    if not item.source_item_id or not client.configured:
        return [], True

    breaker_open = False
    with contextlib.suppress(RedisError):
        breaker_open = bool(await redis.exists(_BREAKER_KEY))

    if not breaker_open and await _budget_ok(redis, budget_per_minute):
        try:
            offers = await client.offers(item.source_item_id, timeout=timeout_seconds)
        except (CsmarketRateLimitedError, CsmarketUnavailableError) as exc:
            log.warning(
                "skins.listings.breaker_open",
                source="csmarket",
                slug=item.slug,
                error=str(exc)[:120],
            )
            with contextlib.suppress(RedisError):
                await redis.set(_BREAKER_KEY, "1", ex=BREAKER_TTL)
        except CsmarketError as exc:
            # ``item_not_found``: the item left csmarket since the last feed tick.
            log.warning("skins.listings.refused", source="csmarket", slug=item.slug, code=exc.code)
            if exc.code == "item_not_found":
                return [], False
        except Exception as exc:  # noqa: BLE001 -- an item page must render whatever csmarket does
            log.warning(
                "skins.listings.unexpected", source="csmarket", slug=item.slug, error=str(exc)[:120]
            )
        else:
            rows = await _without_gone(
                redis,
                item.slug,
                sorted(
                    (to_listing(o) for o in offers), key=lambda r: (r.price_units, r.listing_id)
                ),
            )
            payload = json.dumps([asdict(r) for r in rows])
            with contextlib.suppress(RedisError):
                await redis.set(key, payload, ex=FRESH_TTL)
                await redis.set(f"{key}:stale", payload, ex=STALE_TTL)
            return rows, False

    with contextlib.suppress(RedisError):
        stale = await redis.get(f"{key}:stale")
        if stale is not None:
            return await _without_gone(
                redis, item.slug, [Listing(**e) for e in json.loads(stale)]
            ), True
    return [], True


__all__ = [
    "BREAKER_TTL",
    "FRESH_TTL",
    "STALE_TTL",
    "OfferClient",
    "cache_key",
    "csmarket_listings_for",
    "forget",
    "listing_id_for",
    "to_listing",
]
