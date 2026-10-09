"""Is the lot the buyer picked still for sale? Asked before the order exists (ADR-0098).

The offers list a buyer picks from trails the market by minutes: csmarket rebuilds LIS-SKINS
lots from a five-minute export, and both caches add a little. The cheapest lots of a popular
skin sell inside that window, so without a look before payment a buyer paid, waited and got
a refund — four times in one evening for one AK-47 Searing Rage (2026-10-09).

:func:`precheck_order` runs at the top of ``POST /orders``, **before** the order route
touches the database for anything else: it reads each skin line's csmarket item id, ends
that read transaction, and only then asks csmarket's ``GET /catalog/{item}/offers/{offer}``
(``CsmarketClient.check_offer``, ≤ 6 s). No pool connection is held across the call
(AGENTS.md §10). The verdicts go to ``skins.checkout.price_skin_line`` through a
``ContextVar`` — the same task, so nothing is threaded through the order service.

It never raises and never refuses on its own: a repeated ``Idempotency-Key`` must still get
the order it already made, so the verdict is only *read* when a new skin line is priced.
A lot reported ``gone`` evicts the item's cached offers at once.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.suppliers.csmarket_client import OfferStatus
from yupay.modules.skins.listings_csmarket import csmarket_listings_for, forget
from yupay.modules.skins.listings_source import csmarket_client
from yupay.modules.skins.models import SkinItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.orders.schemas import OrderCreate

log = get_logger("yupay.skins.offer_check")


@dataclass(frozen=True)
class OfferVerdict:
    """csmarket's answer for one picked lot; ``price_units`` is our cost on the key's tariff."""

    status: OfferStatus
    price_units: int | None


_VERDICTS: ContextVar[dict[tuple[str, int], OfferVerdict] | None] = ContextVar(
    "skin_offer_verdicts", default=None
)


def verdict_for(slug: str, listing_id: int) -> OfferVerdict | None:
    """The verdict :func:`precheck_order` reached for this line, if it ran."""
    found = _VERDICTS.get()
    return None if found is None else found.get((slug, listing_id))


def _skin_lines(body: OrderCreate) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for line in body.items:
        data = line.fulfillment_data or {}
        slug, listing = data.get("slug"), data.get("listing_id")
        if not isinstance(slug, str) or not slug or not data.get("tradelink"):
            continue
        try:
            out.append((slug, int(listing)))  # type: ignore[arg-type] # checked by the except
        except (TypeError, ValueError):
            continue
    return out


async def _verdicts(
    db: AsyncSession, lines: list[tuple[str, int]]
) -> dict[tuple[str, int], OfferVerdict]:
    rows = (
        await db.execute(
            select(SkinItem.slug, SkinItem.source_item_id).where(
                SkinItem.slug.in_({slug for slug, _ in lines})
            )
        )
    ).all()
    source_ids = {str(slug): source for slug, source in rows if source}
    # End the read before any network call: a pool connection must not wait on csmarket.
    await db.rollback()

    settings = get_settings()
    client = csmarket_client()
    redis = get_redis()
    out: dict[tuple[str, int], OfferVerdict] = {}
    for slug, listing_id in lines:
        source_id = source_ids.get(slug)
        if source_id is None:
            continue
        offers, _degraded = await csmarket_listings_for(
            SkinItem(slug=slug, source_item_id=source_id),
            client=client,
            redis=redis,
            budget_per_minute=settings.csmarket_offers_per_minute,
            timeout_seconds=settings.cs2_skins_listings_timeout_seconds,
        )
        chosen = next((o for o in offers if o.listing_id == listing_id), None)
        if chosen is None or chosen.offer_id is None:
            continue  # checkout answers "listing gone" from the list itself
        status, price = await client.check_offer(source_id, chosen.offer_id)
        out[(slug, listing_id)] = OfferVerdict(status=status, price_units=price)
        log.info("skins.offer_check", slug=slug, status=status)
        if status == "gone":
            await forget(redis, slug, chosen.offer_id)
    return out


@contextlib.asynccontextmanager
async def precheck_order(db: AsyncSession, body: OrderCreate) -> AsyncIterator[None]:
    """Check every csmarket skin line of ``body``; the verdicts live for the ``with`` block.

    Use it before the route reads anything else from ``db``::

        async with precheck_order(db, body):
            ...create the order...
    """
    verdicts: dict[tuple[str, int], OfferVerdict] = {}
    settings = get_settings()
    lines = _skin_lines(body)
    if lines and settings.cs2_skins_source == "csmarket" and settings.csmarket_api_key:
        try:
            verdicts = await _verdicts(db, lines)
        except Exception as exc:  # noqa: BLE001 -- a check must never cost a sale
            log.warning("skins.offer_check.failed", error=type(exc).__name__)
    token = _VERDICTS.set(verdicts)
    try:
        yield
    finally:
        _VERDICTS.reset(token)


__all__ = ["OfferVerdict", "precheck_order", "verdict_for"]
