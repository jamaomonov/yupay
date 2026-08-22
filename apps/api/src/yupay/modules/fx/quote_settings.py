"""Load and persist per-quote admin FX overrides.

The hot path (``FxService.get_rate``) reads Redis first. Postgres is the source
of truth and is consulted only on a cache miss, then written back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.modules.fx import cache
from yupay.modules.fx.models import FxQuoteSetting
from yupay.modules.fx.providers.base import Quote

MANUAL_SOURCE = "manual"


def _compact_rate(value: Decimal | None) -> Decimal | None:
    """Drop ``Numeric(20, 10)`` trailing zeros so JSON stays ``12500``."""
    if value is None:
        return None
    text = format(value, "f").rstrip("0").rstrip(".")
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
) -> ManualOverride | None:
    """Redis, then Postgres. Writes Redis on a DB hit (or a short negative cache)."""
    cached = await cache.read_manual(redis, quote)
    if cached is not None:
        return _from_payload(cached)
    if session_factory is None:
        return None
    async with session_factory() as db:
        row = await db.get(FxQuoteSetting, quote.upper())
    if row is None:
        await cache.write_manual_absent(redis, quote)
        return None
    override = _from_row(row)
    await cache.write_manual(
        redis,
        quote=override.quote,
        use_manual=override.use_manual,
        manual_rate=override.manual_rate,
        updated_at=override.updated_at,
    )
    return override


async def list_overrides(db: AsyncSession) -> list[ManualOverride]:
    """All stored quote settings (used by the admin listing)."""
    rows = (await db.execute(select(FxQuoteSetting).order_by(FxQuoteSetting.quote))).scalars()
    return [_from_row(row) for row in rows]


async def upsert_override(
    db: AsyncSession,
    redis: Redis,
    *,
    quote: str,
    use_manual: bool,
    manual_rate: Decimal | None,
    updated_by: str | None,
) -> ManualOverride:
    """Write Postgres + Redis. Leaves the provider rate cache alone."""
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
    override = _from_row(row)
    await cache.write_manual(
        redis,
        quote=override.quote,
        use_manual=override.use_manual,
        manual_rate=override.manual_rate,
        updated_at=override.updated_at,
    )
    return override
