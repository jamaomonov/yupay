"""Redis-backed cache for FX rates.

Two keys per pair:

- ``fx:rate:{base}:{quote}`` — fresh value (TTL = ``fx_cache_fresh_seconds``).
- ``fx:rate:{base}:{quote}:stale`` — last-known-good (TTL = ``fx_cache_stale_seconds``).

A fresh cache hit short-circuits the provider chain. A stale hit is the graceful
degradation when every provider fails.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis

from yupay.modules.fx.providers.base import Quote


def _key(base: str, quote: str, *, stale: bool = False) -> str:
    base_u, quote_u = base.upper(), quote.upper()
    return f"fx:rate:{base_u}:{quote_u}{':stale' if stale else ''}"


def _serialise(q: Quote) -> str:
    return json.dumps(
        {
            "base": q.base,
            "quote": q.quote,
            "rate": str(q.rate),
            "fetched_at": q.fetched_at.isoformat(),
            "source": q.source,
        }
    )


def _deserialise(raw: str) -> Quote:
    data = json.loads(raw)
    return Quote(
        base=data["base"],
        quote=data["quote"],
        rate=Decimal(data["rate"]),
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        source=data["source"],
    )


async def read_fresh(redis: Redis, base: str, quote: str) -> Quote | None:
    """Return the fresh cached :class:`Quote` if any."""
    raw = await redis.get(_key(base, quote))
    return _deserialise(raw) if raw else None


async def read_stale(redis: Redis, base: str, quote: str) -> Quote | None:
    """Return the stale cached :class:`Quote` if any."""
    raw = await redis.get(_key(base, quote, stale=True))
    return _deserialise(raw) if raw else None


async def write(
    redis: Redis,
    q: Quote,
    *,
    fresh_ttl_seconds: int,
    stale_ttl_seconds: int,
) -> None:
    """Store both ``fresh`` and ``:stale`` copies of a quote."""
    payload = _serialise(q)
    await redis.set(_key(q.base, q.quote), payload, ex=fresh_ttl_seconds)
    await redis.set(_key(q.base, q.quote, stale=True), payload, ex=stale_ttl_seconds)


async def invalidate(redis: Redis, base: str, quote: str) -> None:
    """Drop the fresh cache entry (keep stale as a safety net)."""
    await redis.delete(_key(base, quote))
