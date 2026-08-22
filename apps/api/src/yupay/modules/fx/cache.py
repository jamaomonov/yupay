"""Redis-backed cache for FX rates.

Keys per pair:

- ``fx:rate:{base}:{quote}`` — fresh value (TTL = ``fx_cache_fresh_seconds``).
- ``fx:rate:{base}:{quote}:stale`` — last-known-good (TTL = ``fx_cache_stale_seconds``).
- ``fx:manual:{quote}`` — admin override (1 h; written after save / on first DB load).
- ``fx:provider_chain`` — ordered adapter list (no TTL).
- ``fx:failover:{base}:{quote}`` — last failover fingerprint (no TTL).
- ``fx:provider_probe`` — the admin page's live per-adapter probe (60 s).

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

#: The override itself. Postgres is the source of truth, so an entry that
#: outlives its row is a rate nothing supports — and one that never expires
#: outlives it forever. An hour is long enough that the hot path effectively
#: never touches Postgres, and short enough that any divergence heals itself.
MANUAL_TTL_SECONDS = 3600


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


#: The admin FX page's probe. Short, because the page exists to show what the
#: adapters are answering *now* — but not absent, because the probe is a real
#: upstream call per adapter per quote, billed against a quota measured in
#: thousands per month. Without it, every open tab and every reload paid for
#: its own round of them.
PROBE_TTL_SECONDS = 60

_PROBE_KEY = "fx:provider_probe"


async def read_probe(redis: Redis) -> str | None:
    """Raw cached probe JSON, or ``None``."""
    raw = await redis.get(_PROBE_KEY)
    if not raw:
        return None
    return str(raw)


async def write_probe(redis: Redis, payload: str) -> None:
    await redis.set(_PROBE_KEY, payload, ex=PROBE_TTL_SECONDS)


async def clear_probe(redis: Redis) -> None:
    """Drop the cached probe so the next read really goes upstream.

    "Обновить" exists to answer "did my fix land?" — a fixed API key, a
    re-enabled account — and a minute of cached errors is the one answer that
    is useless there.
    """
    await redis.delete(_PROBE_KEY)
