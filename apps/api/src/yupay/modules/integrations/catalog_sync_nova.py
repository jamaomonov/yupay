"""Pull NOVA's catalogue into ``supplier_catalog_cache``.

NOVA has no voucher concept — its whole catalogue is game/top-up categories
(``list_topups()``) plus, per category, a list of purchasable offers
(``get_offers(category_id)``). That second call is the reason denominations
are not swept wholesale: it is one call *per game*, and NOVA's own catalogue
was 306 categories the last time anyone counted (see ``nova_client.py``) —
pulling every one hourly for data almost none of which is ever looked at
would turn a cheap sync into dozens of upstream calls a tick. So, like G2B's
mapped-voucher refresh this module mirrors:

- the full sweep (:func:`sync_nova_catalog`) writes one ``game`` row per
  category, cheap (NOVA's client walks its own cursor, but the whole
  catalogue is at most a few hundred rows) — and then re-reads offers **only**
  for games we already hold an active mapping to, the same restriction
  ``catalog_sync_g2b._refresh_mapped_vouchers`` applies to mapped vouchers;
- an explicit, on-demand call (:func:`sync_nova_game_denominations`) pulls one
  game's offers into the cache for an operator who just picked a game the
  cache has never seen — see ``routes.sync_game_denominations`` for why that
  is a POST and never a GET (AGENTS.md §10).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.catalog_sync_types import CatalogSyncReport
from yupay.modules.integrations.models import NOVA_STEAM_SENTINEL

log = get_logger("yupay.integrations.catalog_sync.nova")

#: Ceiling on the by-category denomination refresh, mirroring G2B's
#: ``_MAPPED_FETCH_CAP`` — a data mistake must not turn one tick into
#: hundreds of ``get_offers`` calls. NOVA is a reserve supplier (see
#: ``fulfillment/suppliers/nova.py``); production maps a handful of SKUs to
#: it today.
_MAPPED_FETCH_CAP = 200


def _nova_client_or_none() -> NovaClient | None:
    """The registered NOVA client iff ``NOVA_API_KEY`` is configured."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    fulfiller = REGISTRY.get("nova")
    if isinstance(fulfiller, NovaFulfiller) and fulfiller.available:
        return fulfiller._client()
    return None


async def _sync_category_denoms(
    db: AsyncSession, client: NovaClient, category_id: str
) -> tuple[int, bool, str | None]:
    """Write one category's offers as ``game_denom`` rows.

    Returns ``(written, missing_upstream, error)``. ``missing_upstream`` is
    ``True`` only for a confirmed 404 — a generic refusal (rate limit, 5xx)
    is reported as ``error`` instead, since guessing "the game is gone" from
    an ambiguous failure would mislead the operator who mapped it.

    The 404-vs-ambiguous-refusal split above is the only thing this function
    promises to discriminate. Everything past a successful ``get_offers`` —
    a non-dict offer, a junk ``price_usd`` that ``Decimal(str(...))`` won't
    parse, a database error mid-upsert — is caught broadly instead, the same
    way ``catalog_sync_g2b._refresh_mapped_vouchers`` catches per product: one
    malformed offer must report as ``error`` on this category, not raise past
    the caller (``routes.sync_catalog`` promises it never does).
    """
    try:
        body = await client.get_offers(category_id)
    except NovaError as exc:
        if exc.status == 404:
            return 0, True, None
        return 0, False, str(exc)[:200]
    except NovaUnavailableError as exc:
        return 0, False, str(exc)[:200]

    written = 0
    try:
        for offer in body.get("offers") or []:
            offer_id = str(offer.get("offer_id") or "").strip()
            if not offer_id:
                continue
            title = str(offer.get("name") or offer_id)[:255]
            price = offer.get("price_usd")
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="nova",
                kind="game_denom",
                external_id=offer_id,
                title=title,
                raw=offer,
                parent_external_id=category_id,
                price_usdt=Decimal(str(price)) if price not in (None, "") else None,
            )
            written += 1
    except Exception as exc:  # noqa: BLE001 -- one malformed offer must not raise past this category
        return written, False, f"malformed offer payload: {exc!s}"[:200]
    return written, False, None


async def _refresh_mapped_game_denoms(db: AsyncSession) -> tuple[int, int, str | None]:
    """Re-read offers for every NOVA game an active mapping points at.

    Mirrors ``catalog_sync_g2b._refresh_mapped_vouchers``: we only ever sell
    what we map, so denominations are kept current for those categories and
    nobody else's. Returns ``(denoms_written, missing_categories, error)``.

    The Steam reserve mapping (:data:`NOVA_STEAM_SENTINEL`) is excluded up
    front, the same way ``price_refresh._fetch_nova_offers_cache`` and
    ``cost_lookup._nova_raw_price`` already exclude it: it has no
    catalogue offers to fetch (ADR-0082 §4), so ``get_offers("steam-topup")``
    is a guaranteed 404 every tick — not a mapping gone upstream, just one
    that was never a catalogue category to begin with.
    """
    client = _nova_client_or_none()
    if client is None:
        return 0, 0, None

    category_ids = [
        category_id
        for category_id in await svc.mapped_external_product_ids(
            db, supplier_slug="nova", kind="game"
        )
        if category_id != NOVA_STEAM_SENTINEL
    ]
    if len(category_ids) > _MAPPED_FETCH_CAP:
        log.warning(
            "integrations.nova.sync.mapped_cap_hit",
            wanted=len(category_ids),
            cap=_MAPPED_FETCH_CAP,
        )
        category_ids = category_ids[:_MAPPED_FETCH_CAP]

    written = 0
    missing = 0
    failures = 0
    for category_id in category_ids:
        count, is_missing, error = await _sync_category_denoms(db, client, category_id)
        written += count
        if is_missing:
            missing += 1
            log.warning("integrations.nova.sync.mapped_game_gone", category_id=category_id)
        elif error:
            failures += 1
            log.warning(
                "integrations.nova.sync.mapped_game_failed", category_id=category_id, error=error
            )

    error = f"{failures} mapped game(s) failed to refresh offers" if failures else None
    return written, missing, error


async def sync_nova_catalog(db: AsyncSession) -> CatalogSyncReport:
    """Refresh the NOVA half of ``supplier_catalog_cache``.

    Best-effort: the category sweep and the mapped-denomination refresh are
    independent, so one failing does not lose the other. Never raises — the
    route (``routes.sync_catalog``) and the scheduler tick both depend on
    that. The caller commits.
    """
    client = _nova_client_or_none()
    if client is None:
        return CatalogSyncReport(error="NOVA_API_KEY is not configured")

    games = 0
    error: str | None = None
    try:
        categories: list[dict[str, Any]] = await client.list_topups()
        for item in categories:
            external_id = str(item.get("category_id") or "").strip()
            if not external_id:
                continue
            title = str(item.get("name") or external_id)[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="nova",
                kind="game",
                external_id=external_id,
                title=title,
                raw=item,
            )
            games += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        error = f"game sync failed: {exc!s}"[:200]
        log.warning("integrations.nova.sync.games_failed", error=str(exc))

    try:
        mapped, missing, mapped_error = await _refresh_mapped_game_denoms(db)
    except Exception as exc:  # noqa: BLE001 -- best-effort sync, mirrors the games-sweep catch above
        mapped, missing = 0, 0
        mapped_error = f"mapped denom refresh failed: {exc!s}"[:200]
        log.warning("integrations.nova.sync.mapped_denoms_failed", error=str(exc))
    if mapped_error:
        error = f"{error}; {mapped_error}" if error else mapped_error

    return CatalogSyncReport(
        games=games,
        mapped_vouchers=mapped,
        missing_upstream=missing,
        error=error,
    )


async def sync_nova_game_denominations(db: AsyncSession, *, game_id: str) -> tuple[int, str | None]:
    """On-demand: pull one NOVA category's offers into the cache.

    The one live NOVA call this module makes outside the hourly tick, and it
    happens only when an operator explicitly asks for it — see
    ``routes.sync_game_denominations`` for the POST that calls this and why a
    GET handler never may (AGENTS.md §10).
    """
    client = _nova_client_or_none()
    if client is None:
        return 0, "NOVA_API_KEY is not configured"
    written, missing, error = await _sync_category_denoms(db, client, game_id)
    if missing:
        return 0, f"nova has no category {game_id!r}"
    return written, error


__all__ = ["sync_nova_catalog", "sync_nova_game_denominations"]
