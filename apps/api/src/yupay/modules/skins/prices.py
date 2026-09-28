"""Fold Waxpeer's CSV snapshot onto ``skin_items`` every five minutes (spec §4.3).

Streamed, never buffered: 1.19 M rows become ~24 000 aggregates in one
pass. Then, in one transaction: rows whose ``price_hash`` changed are
updated, rows absent from the snapshot go inactive, names the catalogue
has never seen get a stub row from ``/v1/prices`` metadata, and the
catalogue cache version is bumped so every cached page expires at once.
"""

from __future__ import annotations

import contextlib
import hashlib
import heapq
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.waxpeer_client import SnapshotRow, WaxpeerClient
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.naming import canonical_name, parse_market_name, search_text, slug_for
from yupay.modules.skins.taxonomy import category_for_waxpeer_type

log = get_logger("yupay.skins.prices")

CATALOG_VERSION_KEY = "skins:catalog:ver"
CHEAPEST_KEPT = 10
_BATCH = 1000


@dataclass
class PriceAggregate:
    """Everything the snapshot says about one canonical name."""

    min_auto: int | None = None
    count_auto: int = 0
    #: ``(item_id, price_units)`` of the cheapest auto listings, ascending, ≤ 10.
    cheapest: list[tuple[int, int]] = field(default_factory=list)
    min_all: int | None = None
    count_all: int = 0
    #: max-heap of ``(-price, item_id)`` used while aggregating; dropped afterwards.
    _heap: list[tuple[int, int]] = field(default_factory=list, repr=False)


@dataclass(frozen=True)
class ApplyResult:
    changed: int
    deactivated: int
    stubs: int


def _fold(out: dict[tuple[str, str], PriceAggregate], row: SnapshotRow) -> None:
    """Fold one listing into its canonical name's aggregate."""
    key = canonical_name(row.name)
    agg = out.get(key)
    if agg is None:
        agg = out[key] = PriceAggregate()
    agg.count_all += 1
    if agg.min_all is None or row.price_units < agg.min_all:
        agg.min_all = row.price_units
    if not row.auto:
        return
    agg.count_auto += 1
    if agg.min_auto is None or row.price_units < agg.min_auto:
        agg.min_auto = row.price_units
    entry = (-row.price_units, row.item_id)
    if len(agg._heap) < CHEAPEST_KEPT:
        heapq.heappush(agg._heap, entry)
    elif entry > agg._heap[0]:
        heapq.heapreplace(agg._heap, entry)


def _finish(out: dict[tuple[str, str], PriceAggregate]) -> dict[tuple[str, str], PriceAggregate]:
    """Turn every heap into the ascending ``cheapest`` list and drop it."""
    for agg in out.values():
        agg.cheapest = sorted(
            ((item_id, -neg) for neg, item_id in agg._heap), key=lambda t: (t[1], t[0])
        )
        agg._heap = []
    return out


def aggregate(rows: Iterable[SnapshotRow]) -> dict[tuple[str, str], PriceAggregate]:
    """One pass over the rows; the key is ``naming.canonical_name`` of the listing name."""
    out: dict[tuple[str, str], PriceAggregate] = {}
    for row in rows:
        _fold(out, row)
    return _finish(out)


async def aggregate_stream(
    rows: AsyncIterator[SnapshotRow],
) -> dict[tuple[str, str], PriceAggregate]:
    """The streaming twin of :func:`aggregate`: same folding, one row in memory at a time."""
    out: dict[tuple[str, str], PriceAggregate] = {}
    async for row in rows:
        _fold(out, row)
    return _finish(out)


def price_hash(agg: PriceAggregate) -> str:
    """Stable digest of the price columns, so an unchanged row costs no UPDATE."""
    parts = [
        str(agg.min_auto),
        str(agg.count_auto),
        ",".join(f"{i}:{p}" for i, p in agg.cheapest),
        str(agg.min_all),
        str(agg.count_all),
    ]
    # Change detection, not security: a collision costs one skipped UPDATE.
    return hashlib.sha1("|".join(parts).encode()).hexdigest()  # noqa: S324


def _meta_by_name(meta: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {canonical_name(str(m.get("name", ""))): m for m in meta if m.get("name")}


async def apply_prices(
    db: AsyncSession,
    aggregates: Mapping[tuple[str, str], PriceAggregate],
    *,
    meta: Iterable[Mapping[str, Any]],
    at: datetime,
) -> ApplyResult:
    """Write the aggregates onto ``skin_items``: changed rows, deactivations, stubs."""
    existing = (
        await db.execute(
            select(SkinItem.id, SkinItem.market_hash_name, SkinItem.phase, SkinItem.price_hash)
        )
    ).all()
    by_key = {(name, phase): (item_id, digest) for item_id, name, phase, digest in existing}
    meta_by_key = _meta_by_name(meta)

    updates: list[dict[str, Any]] = []
    stubs: list[dict[str, Any]] = []
    for key, agg in aggregates.items():
        digest = price_hash(agg)
        steam = meta_by_key.get(key, {}).get("steam_price")
        values = {
            "min_auto_units": agg.min_auto,
            "count_auto": agg.count_auto,
            "cheapest_auto": [
                {"listing_id": item_id, "price_units": price} for item_id, price in agg.cheapest
            ],
            "min_all_units": agg.min_all,
            "count_all": agg.count_all,
            "steam_price_units": int(steam) if isinstance(steam, int | float) else None,
            "price_hash": digest,
            "prices_updated_at": at,
            "active": agg.count_auto > 0,
            "updated_at": at,
        }
        found = by_key.get(key)
        if found is None:
            name, phase = key
            parsed = parse_market_name(name)
            m = meta_by_key.get(key, {})
            stubs.append(
                {
                    "id": new_id(),
                    "market_hash_name": name,
                    "phase": phase,
                    "slug": slug_for(name, phase),
                    "category": category_for_waxpeer_type(m.get("type")),
                    "weapon": parsed.weapon,
                    "skin": parsed.skin,
                    "exterior": parsed.exterior,
                    "stattrak": parsed.stattrak,
                    "souvenir": parsed.souvenir,
                    "rarity": m.get("rarity"),
                    "rarity_color": m.get("rarity_color"),
                    "image_url": None,  # Waxpeer's CDN is never stored; the import fills it
                    "source": "stub",
                    "search_text": search_text(name, phase),
                    **values,
                }
            )
        elif found[1] != digest:
            updates.append({"id": found[0], **values})

    for start in range(0, len(updates), _BATCH):
        await db.execute(update(SkinItem), updates[start : start + _BATCH])
    for start in range(0, len(stubs), _BATCH):
        await db.execute(
            pg_insert(SkinItem)
            .values(stubs[start : start + _BATCH])
            .on_conflict_do_nothing(constraint="uq_skin_items_name_phase")
        )

    missing = [item_id for key, (item_id, _) in by_key.items() if key not in aggregates]
    deactivated = 0
    if missing:
        result = await db.execute(
            update(SkinItem)
            .where(SkinItem.id.in_(missing), SkinItem.active.is_(True))
            .values(
                active=False,
                min_auto_units=None,
                count_auto=0,
                cheapest_auto=[],
                price_hash=None,
                prices_updated_at=at,
                updated_at=at,
            )
        )
        # ``rowcount`` lives on CursorResult; async ``execute`` is typed as Result.
        deactivated = int(getattr(result, "rowcount", 0) or 0)
    return ApplyResult(changed=len(updates), deactivated=deactivated, stubs=len(stubs))


async def bump_catalog_version(redis: Redis) -> None:
    """Every cached catalogue page carries this number in its key; +1 expires them all."""
    with contextlib.suppress(RedisError):
        await redis.incr(CATALOG_VERSION_KEY)


async def sync_prices(
    session_factory: async_sessionmaker[AsyncSession],
    client: WaxpeerClient,
    redis: Redis,
) -> ApplyResult:
    """One tick: stream the snapshot, read ``/v1/prices``, apply, bump the version."""
    aggregates = await aggregate_stream(client.iter_snapshot_rows())
    meta = await client.prices()
    async with session_factory() as db:
        result = await apply_prices(db, aggregates, meta=meta, at=now())
        await db.commit()
    await bump_catalog_version(redis)
    log.info(
        "skins.prices.synced",
        names=len(aggregates),
        changed=result.changed,
        deactivated=result.deactivated,
        stubs=result.stubs,
    )
    return result


__all__ = [
    "CATALOG_VERSION_KEY",
    "ApplyResult",
    "PriceAggregate",
    "aggregate",
    "aggregate_stream",
    "apply_prices",
    "bump_catalog_version",
    "price_hash",
    "sync_prices",
]
