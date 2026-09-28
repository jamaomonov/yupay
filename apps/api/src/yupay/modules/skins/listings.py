"""The one catalogue read that can reach Waxpeer (spec §4.5, AGENTS.md §10).

Order of attempts for one item: fresh Redis → (breaker closed and budget
left) live search v2 → stale Redis → the snapshot's ``cheapest_auto``.
``degraded`` tells the page it is looking at something less than a live
answer, so it can say "цены обновлены N минут назад" rather than pretend.

Never raises for a supplier problem: an item page must render whatever
Waxpeer is doing.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)
from yupay.modules.skins.models import SkinItem

log = get_logger("yupay.skins.listings")

FRESH_TTL = 90
STALE_TTL = 3600
BREAKER_TTL = 120
_BUDGET_TTL = 120


class SearchClient(Protocol):
    async def search_listings(
        self, names: list[str], *, game: str = "csgo"
    ) -> dict[str, list[dict[str, Any]]]: ...


@dataclass(frozen=True)
class Listing:
    listing_id: int
    price_units: int
    float_value: float | None
    paint_seed: int | None
    stickers: list[dict[str, Any]]
    inspect_url: str | None
    delivery: str | None


def _parse(raw: dict[str, Any]) -> Listing | None:
    try:
        listing_id = int(raw["item_id"])
        price = int(raw["price"])
    except (KeyError, TypeError, ValueError):
        return None
    float_value = raw.get("float")
    seed = raw.get("paintseed")
    stickers = [
        {k: s.get(k) for k in ("name", "image", "slot", "wear")}
        for s in raw.get("stickers") or []
        if isinstance(s, dict) and s.get("name")
    ]
    return Listing(
        listing_id=listing_id,
        price_units=price,
        float_value=float(float_value) if isinstance(float_value, int | float) else None,
        paint_seed=int(seed) if isinstance(seed, int) else None,
        stickers=stickers,
        inspect_url=raw.get("inspect") if isinstance(raw.get("inspect"), str) else None,
        delivery=raw.get("delivery") if isinstance(raw.get("delivery"), str) else None,
    )


def _from_snapshot(item: SkinItem) -> list[Listing]:
    return [
        Listing(
            listing_id=int(e["listing_id"]),
            price_units=int(e["price_units"]),
            float_value=None,
            paint_seed=None,
            stickers=[],
            inspect_url=None,
            delivery=None,
        )
        for e in item.cheapest_auto
    ]


def _waxpeer_name(item: SkinItem) -> str:
    """The name as Waxpeer spells it — the phase back inside, before the wear."""
    if not item.phase:
        return item.market_hash_name
    head, _, tail = item.market_hash_name.rpartition(" (")
    return f"{head} {item.phase} ({tail}" if tail else f"{item.market_hash_name} {item.phase}"


async def _budget_ok(redis: Redis, limit: int) -> bool:
    if limit <= 0:
        return False
    key = f"skins:wax:budget:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    with contextlib.suppress(RedisError):
        used = await redis.incr(key)
        await redis.expire(key, _BUDGET_TTL)
        return int(used) <= limit
    return True


async def listings_for(
    item: SkinItem, *, client: SearchClient, redis: Redis, budget_per_minute: int
) -> tuple[list[Listing], bool]:
    """``(listings, degraded)`` for one item — see the module docstring for the order."""
    key = f"skins:listings:{item.slug}"
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
        if cached is not None:
            return [Listing(**e) for e in json.loads(cached)], False

    breaker_open = False
    with contextlib.suppress(RedisError):
        breaker_open = bool(await redis.exists("skins:wax:breaker"))

    if not breaker_open and await _budget_ok(redis, budget_per_minute):
        name = _waxpeer_name(item)
        try:
            found = await client.search_listings([name])
        except (WaxpeerRateLimitedError, WaxpeerUnavailableError) as exc:
            log.warning("skins.listings.breaker_open", slug=item.slug, error=str(exc)[:120])
            with contextlib.suppress(RedisError):
                await redis.set("skins:wax:breaker", "1", ex=BREAKER_TTL)
        except WaxpeerError as exc:
            log.warning("skins.listings.refused", slug=item.slug, error=str(exc)[:120])
        else:
            rows = [
                listing
                for raw in found.get(name, [])
                if raw.get("auto") is True and (listing := _parse(raw)) is not None
            ]
            rows.sort(key=lambda row: (row.price_units, row.listing_id))
            payload = json.dumps([asdict(r) for r in rows])
            with contextlib.suppress(RedisError):
                await redis.set(key, payload, ex=FRESH_TTL)
                await redis.set(f"{key}:stale", payload, ex=STALE_TTL)
            return rows, False

    with contextlib.suppress(RedisError):
        stale = await redis.get(f"{key}:stale")
        if stale is not None:
            return [Listing(**e) for e in json.loads(stale)], True
    return _from_snapshot(item), True


__all__ = ["BREAKER_TTL", "FRESH_TTL", "STALE_TTL", "Listing", "listings_for"]
