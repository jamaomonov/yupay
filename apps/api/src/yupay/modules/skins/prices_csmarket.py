"""Fold the csmarket feed onto ``skin_items`` (ADR-0098) — the csmarket twin of ``prices``.

One pass reads every page of ``GET /catalog`` (~15 000 items, 16 pages, a few seconds) on
the key's ``cost`` tariff. Each item becomes one :class:`~yupay.modules.skins.prices.
PriceAggregate`: the cheapest offer's cost is ``min_auto`` and the offer count is
``count_auto``. The feed lists only instant offers, so the ``_all`` columns repeat them, and
it names no individual offers, so ``cheapest`` stays empty — an item page reads the live
offers instead.

Join key: ``(market_hash_name, phase)``, as for Waxpeer. csmarket writes the name without
the Doppler phase and puts the phase only in its slug, which it builds with the same
``slug_for`` as ours; the phase is read back from the slug's tail.

Everything after the aggregation is ``prices.apply_prices`` with ``meta=None`` (the feed has
no Steam price, so the last known one is kept) and the csmarket item ids, then the same
repricing and cache bump as the Waxpeer tick.
"""

from __future__ import annotations

from collections.abc import AsyncIterable

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.csmarket_client import CsmarketClient, FeedItem
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.naming import PHASES, canonical_name, slug_for
from yupay.modules.skins.prices import (
    MIN_SNAPSHOT_SHARE,
    ApplyResult,
    PriceAggregate,
    apply_prices,
    bump_catalog_version,
)
from yupay.modules.skins.repricing import lock_pricing, reprice_rows
from yupay.modules.skins.settings import load_rules

log = get_logger("yupay.skins.prices_csmarket")

#: ``"phase-2"`` → ``"Phase 2"``, ``"black-pearl"`` → ``"Black Pearl"``.
_PHASE_BY_SLUG: dict[str, str] = {slug_for(phase, ""): phase for phase in PHASES}


def key_of(item: FeedItem) -> tuple[str, str]:
    """``(market_hash_name, phase)`` for a feed item.

    A name that already carries an inline phase (Waxpeer's spelling) is canonicalised the
    usual way; otherwise the phase is the slug's tail after the phase-less slug.
    """
    name, phase = canonical_name(item.market_hash_name)
    if phase:
        return name, phase
    base = slug_for(name, "")
    if item.slug.startswith(f"{base}-"):
        found = _PHASE_BY_SLUG.get(item.slug[len(base) + 1 :])
        if found:
            return name, found
    return name, ""


async def aggregate_feed(
    items: AsyncIterable[FeedItem],
) -> tuple[dict[tuple[str, str], PriceAggregate], dict[tuple[str, str], str]]:
    """``(aggregates, csmarket item ids)`` keyed by ``(market_hash_name, phase)``.

    Two feed rows on one key (never seen, but the slug is the only phase signal) keep the
    cheaper one and its id.
    """
    aggregates: dict[tuple[str, str], PriceAggregate] = {}
    ids: dict[tuple[str, str], str] = {}
    async for item in items:
        if item.stock <= 0:
            continue
        key = key_of(item)
        held = aggregates.get(key)
        if held is not None and held.min_auto is not None and held.min_auto <= item.price_units:
            continue
        aggregates[key] = PriceAggregate(
            min_auto=item.price_units,
            count_auto=item.stock,
            cheapest=[],
            min_all=item.price_units,
            count_all=item.stock,
        )
        ids[key] = item.item_id
    return aggregates, ids


async def sync_prices_csmarket(
    session_factory: async_sessionmaker[AsyncSession],
    client: CsmarketClient,
    redis: Redis,
) -> ApplyResult:
    """One tick: read the whole feed, apply it, reprice, bump the catalogue version."""
    aggregates, ids = await aggregate_feed(client.iter_catalog())
    async with session_factory() as db:
        active_before = int(
            (
                await db.execute(
                    select(func.count()).select_from(SkinItem).where(SkinItem.active.is_(True))
                )
            ).scalar_one()
        )
        # Same guard as the Waxpeer tick: a short feed must not read as "sold out".
        # The first csmarket tick after a switch compares against Waxpeer's catalogue,
        # which is ~10 % larger (ADR-0098) — well inside the 50 % floor.
        if active_before and len(aggregates) < active_before * MIN_SNAPSHOT_SHARE:
            log.warning(
                "skins.prices.refused",
                source="csmarket",
                names=len(aggregates),
                active_before=active_before,
                reason="feed far smaller than the live catalogue",
            )
            return ApplyResult(changed=0, deactivated=0, stubs=0)
        await lock_pricing(db)
        result = await apply_prices(db, aggregates, meta=None, at=now(), source_ids=ids)
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
    await bump_catalog_version(redis)
    log.info(
        "skins.prices.synced",
        source="csmarket",
        names=len(aggregates),
        changed=result.changed,
        deactivated=result.deactivated,
        stubs=result.stubs,
    )
    return result


__all__ = ["aggregate_feed", "key_of", "sync_prices_csmarket"]
