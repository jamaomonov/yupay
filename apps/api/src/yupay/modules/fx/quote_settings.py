"""Load and persist per-quote admin FX overrides.

The hot path (``FxService.get_rate``) reads Redis first. Postgres is the source
of truth and is consulted only on a cache miss, then written back.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.modules.fx import cache
from yupay.modules.fx.models import FxQuoteSetting
from yupay.modules.fx.providers.base import Quote
from yupay.modules.fx.session_source import fx_session

MANUAL_SOURCE = "manual"


def _compact_rate(value: Decimal | None) -> Decimal | None:
    """Drop ``Numeric(20, 10)`` trailing zeros so JSON stays ``12500``.

    Only the fractional part is stripped. Stripping unconditionally eats the
    significant zeros of a whole number — 12500 came back 125 — and a manual
    rate skips the pricing band by design (ADR-0055), so nothing downstream
    would have questioned it.
    """
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text or "0")


@dataclass(frozen=True)
class ManualOverride:
    """Admin setting for one USD→quote pair."""

    quote: str
    use_manual: bool
    manual_rate: Decimal | None
    updated_at: datetime | None


def override_to_quote(row: ManualOverride, *, base: str = "USD") -> Quote | None:
    """Return a :class:`Quote` when the toggle is on and a rate is set."""
    if not row.use_manual or row.manual_rate is None:
        return None
    return Quote(
        base=base.upper(),
        quote=row.quote.upper(),
        rate=row.manual_rate,
        fetched_at=row.updated_at or now(),
        source=MANUAL_SOURCE,
    )


def _from_payload(data: dict[str, object]) -> ManualOverride:
    raw_rate = data.get("manual_rate")
    raw_at = data.get("updated_at")
    return ManualOverride(
        quote=str(data.get("quote", "")).upper(),
        use_manual=bool(data.get("use_manual")),
        manual_rate=Decimal(raw_rate) if isinstance(raw_rate, str) else None,
        updated_at=datetime.fromisoformat(raw_at) if isinstance(raw_at, str) else None,
    )


def _from_row(row: FxQuoteSetting) -> ManualOverride:
    return ManualOverride(
        quote=row.quote.upper(),
        use_manual=row.use_manual,
        manual_rate=_compact_rate(row.manual_rate),
        updated_at=row.updated_at,
    )


async def load_override(
    redis: Redis,
    quote: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
    db: AsyncSession | None = None,
) -> ManualOverride | None:
    """Redis, then Postgres. Writes Redis on a DB hit (or a short negative cache).

    A Redis failure is not an answer, but this path has a real one behind it:
    Postgres holds the same row, and reaching it costs a query rather than a
    500. Distinct from the rate cache, where the fallback is an outbound HTTP
    call and swallowing the error would turn a blip into a provider stampede.
    """
    cached = None
    with contextlib.suppress(RedisError):
        cached = await cache.read_manual(redis, quote)
    if cached is not None:
        return _from_payload(cached)
    async with fx_session(db=db, session_factory=session_factory) as session:
        if session is None:
            return None
        row = await session.get(FxQuoteSetting, quote.upper())
    if row is None:
        await cache.write_manual_absent(redis, quote)
        return None
    override = _from_row(row)
    await publish_override(redis, override)
    return override


async def list_overrides(db: AsyncSession) -> list[ManualOverride]:
    """All stored quote settings (used by the admin listing)."""
    rows = (await db.execute(select(FxQuoteSetting).order_by(FxQuoteSetting.quote))).scalars()
    return [_from_row(row) for row in rows]


async def upsert_override(
    db: AsyncSession,
    *,
    quote: str,
    use_manual: bool,
    manual_rate: Decimal | None,
    updated_by: str | None,
) -> ManualOverride:
    """Write Postgres only. Leaves both caches alone.

    Publishing to Redis is the caller's job, **after** it commits. Writing the
    override here meant an uncommitted rate was already live: if anything after
    the flush failed — the commit itself, the idempotency-replay write, the 503
    when FX is unavailable — Postgres rolled back and Redis kept serving a rate
    no row supported. The admin page reads the toggle from Postgres, so the
    divergence would not even have been visible.
    """
    quote_u = quote.upper()
    row = await db.get(FxQuoteSetting, quote_u)
    if row is None:
        row = FxQuoteSetting(quote=quote_u, use_manual=False, manual_rate=None)
        db.add(row)
    row.use_manual = use_manual
    if manual_rate is not None:
        row.manual_rate = manual_rate
    row.updated_at = now()
    row.updated_by = updated_by
    await db.flush()
    return _from_row(row)


async def publish_override(redis: Redis, override: ManualOverride) -> None:
    """Push a committed override into Redis."""
    await cache.write_manual(
        redis,
        quote=override.quote,
        use_manual=override.use_manual,
        manual_rate=override.manual_rate,
        updated_at=override.updated_at,
        ttl_seconds=cache.MANUAL_TTL_SECONDS,
    )
