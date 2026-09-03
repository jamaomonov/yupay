"""Load and persist the admin-editable Steam Gifts margin.

Same shape as ``fx.quote_settings``: the hot path reads Redis first, Postgres
is the source of truth on a cache miss, and a save only ever touches Postgres
— the caller publishes to Redis itself, and only **after** its own commit
lands (see :func:`publish_margin`).
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.redis import get_redis
from yupay.modules.gifts.models import SteamGiftSettings

_MARGIN_KEY = "gifts:margin"
_MARGIN_TTL_SECONDS = 3600


async def load_margin_percent(db: AsyncSession) -> Decimal:
    """The live margin: Redis, then Postgres row 1, then the env-seeded default.

    A Redis error (not merely a miss) is swallowed — the read falls through
    to Postgres exactly as a cold cache would, per the fail-open posture in
    ``core.redis``.
    """
    redis = get_redis()
    with contextlib.suppress(RedisError):
        cached = await redis.get(_MARGIN_KEY)
        if cached is not None:
            return Decimal(cached.decode() if isinstance(cached, bytes) else str(cached))
    row = await db.get(SteamGiftSettings, 1)
    value = row.margin_percent if row is not None else get_settings().steam_gifts_margin_percent
    with contextlib.suppress(RedisError):
        await redis.set(_MARGIN_KEY, str(value), ex=_MARGIN_TTL_SECONDS)
    return value


async def save_margin_percent(db: AsyncSession, *, value: Decimal, admin_id: str) -> None:
    """Upsert row 1 with the new margin. Postgres only — no cache write.

    Publishing to Redis is the caller's job, **after** it commits — same
    invariant as ``fx.quote_settings.upsert_override``: writing the cache
    here would make an uncommitted margin live, and a rollback (or a later
    failure in the same request) would leave Redis serving a value no row
    supports.
    """
    row = await db.get(SteamGiftSettings, 1)
    if row is None:
        row = SteamGiftSettings(id=1, margin_percent=value, updated_by=admin_id)
        db.add(row)
    else:
        row.margin_percent = value
        row.updated_by = admin_id
        row.updated_at = now()
    await db.flush()


async def publish_margin(value: Decimal) -> None:
    """Push a committed margin into Redis. Call only after ``db.commit()``."""
    redis = get_redis()
    await redis.set(_MARGIN_KEY, str(value), ex=_MARGIN_TTL_SECONDS)


def offered_zones(settings: Settings) -> list[str]:
    """Parse ``settings.steam_gifts_regions`` into upper-cased, deduped zone codes.

    Order is first-seen order from the CSV, not sorted — the admin UI and any
    default-selection logic rely on the configured order being meaningful
    (e.g. the first zone as a fallback).
    """
    seen: set[str] = set()
    zones: list[str] = []
    for raw in settings.steam_gifts_regions.split(","):
        zone = raw.strip().upper()
        if not zone or zone in seen:
            continue
        seen.add(zone)
        zones.append(zone)
    return zones


def default_zone(settings: Settings) -> str:
    """The upper-cased default zone (``settings.steam_gifts_region_default``)."""
    return settings.steam_gifts_region_default.strip().upper()


__all__ = [
    "default_zone",
    "load_margin_percent",
    "offered_zones",
    "publish_margin",
    "save_margin_percent",
]
