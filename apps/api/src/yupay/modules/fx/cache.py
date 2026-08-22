"""Redis-backed cache for FX rates.

Keys per pair:

- ``fx:rate:{base}:{quote}`` — fresh value (TTL = ``fx_cache_fresh_seconds``).
- ``fx:rate:{base}:{quote}:stale`` — last-known-good (TTL = ``fx_cache_stale_seconds``).
- ``fx:manual:{quote}`` — admin override (no TTL; written on save / first DB load).
- ``fx:provider_chain`` — ordered adapter list (no TTL).
- ``fx:failover:{base}:{quote}`` — last failover fingerprint (no TTL).

A fresh cache hit short-circuits the provider chain. A stale hit is the graceful
degradation when every provider fails. A manual override short-circuits both.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
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


async def invalidate_fresh_many(redis: Redis, quotes: Sequence[str], *, base: str = "USD") -> None:
    """Drop fresh entries so the next read hits the (possibly reordered) chain."""
    if quotes:
        await redis.delete(*(_key(base, quote) for quote in quotes))


MANUAL_ABSENT_TTL_SECONDS = 60


def _manual_key(quote: str) -> str:
    return f"fx:manual:{quote.upper()}"


async def read_manual(redis: Redis, quote: str) -> dict[str, object] | None:
    """Return the cached admin override payload, or ``None`` on a miss.

    A payload with ``use_manual`` false and no rate is a negative cache: we
    already looked in Postgres and there is nothing to apply.
    """
    raw = await redis.get(_manual_key(quote))
    if not raw:
        return None
    data: dict[str, object] = json.loads(raw)
    return data


async def write_manual(
    redis: Redis,
    *,
    quote: str,
    use_manual: bool,
    manual_rate: Decimal | None,
    updated_at: datetime | None,
    ttl_seconds: int | None = None,
) -> None:
    """Persist the admin override. ``ttl_seconds=None`` means no expiry."""
    payload = json.dumps(
        {
            "quote": quote.upper(),
            "use_manual": use_manual,
            "manual_rate": str(manual_rate) if manual_rate is not None else None,
            "updated_at": updated_at.isoformat() if updated_at is not None else None,
        }
    )
    if ttl_seconds is None:
        await redis.set(_manual_key(quote), payload)
    else:
        await redis.set(_manual_key(quote), payload, ex=ttl_seconds)


async def write_manual_absent(redis: Redis, quote: str) -> None:
    """Negative-cache a missing settings row so get_rate does not hit Postgres."""
    await write_manual(
        redis,
        quote=quote,
        use_manual=False,
        manual_rate=None,
        updated_at=None,
        ttl_seconds=MANUAL_ABSENT_TTL_SECONDS,
    )
