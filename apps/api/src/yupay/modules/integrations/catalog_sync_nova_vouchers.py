"""The gift-card half of NOVA's catalogue sync.

``catalog_sync_nova`` opened with "NOVA has no voucher concept — its whole
catalogue is game/top-up categories". That was true of what we had read of
their API, not of their API: ``GET /api/v2/giftcards`` is a second catalogue
of 576 categories, and ``GET /api/v2/giftcards/cards?category_id=…`` is the
ladder inside one, each card carrying its own ``card_id``, ``price_usd`` and
live ``stock``. It was found by reading their OpenAPI at
``/api/openapi.json`` after six guessed paths 404'd — the lesson is recorded
in ``nova_client.list_giftcard_cards``.

Until this module existed, an operator who pressed «Синхронизировать
каталог» got the games and nothing else, which is exactly what was reported
("я только что сделал синхронизацию новы, там синхронизировались только
игры, ваучеры нет").

Same two-level shape and the same restraint as the games half:

* the sweep writes one ``voucher`` row per category — cheap, a cursor walk;
* cards are re-read **only** for categories an active voucher mapping points
  at, because 576 categories × one call each would turn a cheap tick into
  hundreds of upstream requests for rows nobody will look at.

Split into its own module rather than grown inside ``catalog_sync_nova``:
that file was 246 lines and §6 of AGENTS.md puts the ceiling at 400. The
seam is the catalogue, not the supplier — games there, gift cards here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)
from yupay.modules.integrations import service as svc

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.integrations.catalog_sync.nova_vouchers")

#: Ceiling on the by-category card refresh, mirroring the games half's
#: ``_MAPPED_FETCH_CAP``. A data mistake must not turn one tick into hundreds
#: of ``list_giftcard_cards`` calls.
_MAPPED_FETCH_CAP = 200


async def sync_giftcard_categories(db: AsyncSession, client: NovaClient) -> tuple[int, str | None]:
    """Write one ``voucher`` row per gift-card category.

    Args:
        db: Session. The caller commits.
        client: A configured NOVA client.

    Returns:
        ``(written, error)``. Never raises — ``sync_nova_catalog`` promises
        its own caller that much, and a gift-card failure must not lose the
        games sweep that ran beside it.
    """
    written = 0
    try:
        for item in await client.list_giftcards():
            external_id = str(item.get("category_id") or "").strip()
            if not external_id:
                continue
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="nova",
                kind="voucher",
                external_id=external_id,
                title=str(item.get("name") or external_id)[:255],
                raw=item,
            )
            written += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        log.warning("integrations.nova.sync.giftcards_failed", error=str(exc))
        return written, f"gift-card sync failed: {exc!s}"[:200]
    return written, None


async def _sync_category_cards(
    db: AsyncSession, client: NovaClient, category_id: str
) -> tuple[int, bool, str | None]:
    """Write one category's cards as ``voucher_denom`` rows.

    Returns ``(written, missing_upstream, error)``. ``missing_upstream`` is
    ``True`` only for a confirmed 404 — the games half draws the same line,
    and for the same reason: guessing "the category is gone" from a rate
    limit would tell an operator their mapping is dead when it is not.
    """
    try:
        rows = await client.list_giftcard_cards(category_id)
    except NovaError as exc:
        if exc.status == 404:
            return 0, True, None
        return 0, False, str(exc)[:200]
    except NovaUnavailableError as exc:
        return 0, False, str(exc)[:200]

    written = 0
    seen: set[str] = set()
    try:
        for card in rows:
            card_id = str(card.get("card_id") or "").strip()
            if not card_id:
                continue
            seen.add(card_id)
            price = card.get("price_usd")
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="nova",
                kind="voucher_denom",
                external_id=card_id,
                title=str(card.get("name") or card_id)[:255],
                raw=card,
                parent_external_id=category_id,
                price_usdt=Decimal(str(price)) if price not in (None, "") else None,
            )
            written += 1
        # Inside the same ``try`` as the loop, deliberately — see the games
        # half's note. Only a clean pass reaches this line, and an empty
        # ``seen`` prunes nothing by ``prune_catalog_denoms``'s own rule, so
        # neither can read as NOVA delisting a whole category at once.
        await svc.prune_catalog_denoms(
            db, supplier_slug="nova", parent_external_id=category_id, keep=seen
        )
    except Exception as exc:  # noqa: BLE001 -- one malformed card must not raise past this category
        return written, False, f"malformed card payload: {exc!s}"[:200]
    return written, False, None


async def refresh_mapped_giftcards(
    db: AsyncSession, client: NovaClient
) -> tuple[int, int, str | None]:
    """Re-read cards for every NOVA gift-card category we hold a mapping to.

    Args:
        db: Session. The caller commits.
        client: A configured NOVA client.

    Returns:
        ``(cards_written, missing_categories, error)``.
    """
    category_ids = await svc.mapped_external_product_ids(db, supplier_slug="nova", kind="voucher")
    if len(category_ids) > _MAPPED_FETCH_CAP:
        log.warning(
            "integrations.nova.sync.mapped_giftcard_cap_hit",
            wanted=len(category_ids),
            cap=_MAPPED_FETCH_CAP,
        )
        category_ids = category_ids[:_MAPPED_FETCH_CAP]

    written = 0
    missing = 0
    failures = 0
    for category_id in category_ids:
        count, is_missing, error = await _sync_category_cards(db, client, category_id)
        written += count
        if is_missing:
            missing += 1
            log.warning("integrations.nova.sync.mapped_giftcard_gone", category_id=category_id)
        elif error:
            failures += 1
            log.warning(
                "integrations.nova.sync.mapped_giftcard_failed",
                category_id=category_id,
                error=error,
            )

    error = f"{failures} mapped gift-card categor(ies) failed to refresh" if failures else None
    return written, missing, error


async def sync_one_category_cards(
    db: AsyncSession, client: NovaClient, *, category_id: str
) -> tuple[int, str | None]:
    """On-demand: pull one gift-card category's cards into the cache.

    For the operator who has just picked a category the cache has never seen
    — the voucher twin of ``sync_nova_game_denominations``.
    """
    written, missing, error = await _sync_category_cards(db, client, category_id)
    if missing:
        return 0, f"nova has no gift-card category {category_id!r}"
    return written, error


__all__ = [
    "refresh_mapped_giftcards",
    "sync_giftcard_categories",
    "sync_one_category_cards",
]
