"""Pull a panel vendor's catalogue into ``supplier_catalog_cache``.

Shared by ``nova`` and ``fzr``, which publish the same two catalogues
under the same paths. The client carries its own slug, so one call tree
writes rows for whichever vendor was passed in; ``catalog_sync`` binds
the entry points per supplier.

NOVA has **two** catalogues, and this module owns the games half. Its whole
top-up catalogue is game categories (``list_topups()``) plus, per category, a
list of purchasable offers (``get_offers(category_id)``). The gift-card half
— 576 categories, each holding cards with their own price and stock — lives
in ``catalog_sync_panel_vouchers`` and is called from :func:`sync_panel_catalog`
below; until 2026-09-21 it did not exist at all, and pressing
«Синхронизировать каталог» quietly refreshed only the games.

The per-category call is the reason denominations
are not swept wholesale: it is one call *per game*, and NOVA's own catalogue
was 306 categories the last time anyone counted (see ``panel_client.py``) —
pulling every one hourly for data almost none of which is ever looked at
would turn a cheap sync into dozens of upstream calls a tick. So, like G2B's
mapped-voucher refresh this module mirrors:

- the full sweep (:func:`sync_panel_catalog`) writes one ``game`` row per
  category, cheap (NOVA's client walks its own cursor, but the whole
  catalogue is at most a few hundred rows) — and then re-reads offers **only**
  for games we already hold an active mapping to, the same restriction
  ``catalog_sync_g2b._refresh_mapped_vouchers`` applies to mapped vouchers;
- an explicit, on-demand call (:func:`sync_panel_game_denominations`) pulls one
  game's offers into the cache for an operator who just picked a game the
  cache has never seen — see ``routes.sync_game_denominations`` for why that
  is a POST and never a GET (AGENTS.md §10).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.panel_client import (
    PanelClient,
    PanelError,
    PanelUnavailableError,
)
from yupay.modules.integrations import catalog_sync_panel_vouchers as vouchers_sync
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.catalog_sync_types import CatalogSyncReport
from yupay.modules.integrations.models import PANEL_STEAM_SENTINEL

log = get_logger("yupay.integrations.catalog_sync.panel")

#: Ceiling on the by-category denomination refresh, mirroring G2B's
#: ``_MAPPED_FETCH_CAP`` — a data mistake must not turn one tick into
#: hundreds of ``get_offers`` calls. NOVA is a reserve supplier (see
#: ``fulfillment/suppliers/nova.py`` and its fzr twin); production maps a handful of SKUs to
#: it today.
_MAPPED_FETCH_CAP = 200


def _ev(client: PanelClient, name: str) -> str:
    """One log event name, namespaced to the vendor that produced it.

    A function rather than an f-string at each call site: our structured
    logger takes the event as a positional *name*, not a format string.
    """
    return f"integrations.{client.slug}.sync.{name}"


def client_or_none(slug: str) -> PanelClient | None:
    """That vendor's client iff its key is configured.

    Borrowed from the registered fulfiller rather than built here, so the
    credentials and timeout stay in one place. ``None`` — the key is unset —
    is the caller's cue to report "not configured" rather than to fail.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY

    fulfiller = REGISTRY.get(slug)
    reader = getattr(fulfiller, "client_for_reads", None)
    if fulfiller is None or reader is None or not fulfiller.available:
        return None
    client = reader()
    return client if isinstance(client, PanelClient) else None


async def _sync_category_denoms(
    db: AsyncSession, client: PanelClient, category_id: str
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
    except PanelError as exc:
        if exc.status == 404:
            return 0, True, None
        return 0, False, str(exc)[:200]
    except PanelUnavailableError as exc:
        return 0, False, str(exc)[:200]

    written = 0
    seen: set[str] = set()
    try:
        for offer in body.get("offers") or []:
            offer_id = str(offer.get("offer_id") or "").strip()
            if not offer_id:
                continue
            seen.add(offer_id)
            title = str(offer.get("name") or offer_id)[:255]
            price = offer.get("price_usd")
            await svc.upsert_catalog_entry(
                db,
                supplier_slug=client.slug,
                kind="game_denom",
                external_id=offer_id,
                title=title,
                raw=offer,
                parent_external_id=category_id,
                price_usdt=Decimal(str(price)) if price not in (None, "") else None,
            )
            written += 1
        # Inside the same ``try`` as the loop, deliberately: this function
        # promises never to raise past itself (``routes.sync_catalog`` relies
        # on it), and a database error here is exactly as possible as one in
        # ``upsert_catalog_entry`` above.
        #
        # Only a clean pass reaches this line — a partial one returned with an
        # error — and an empty ``seen`` prunes nothing by
        # ``prune_catalog_denoms``'s own rule. Neither may read as a supplier
        # delisting a whole category at once.
        await svc.prune_catalog_denoms(
            db, supplier_slug=client.slug, parent_external_id=category_id, keep=seen
        )
    except Exception as exc:  # noqa: BLE001 -- one malformed offer must not raise past this category
        return written, False, f"malformed offer payload: {exc!s}"[:200]
    return written, False, None


async def _refresh_mapped_game_denoms(
    db: AsyncSession, client: PanelClient
) -> tuple[int, int, str | None]:
    """Re-read offers for every game an active mapping points at.

    Mirrors ``catalog_sync_g2b._refresh_mapped_vouchers``: we only ever sell
    what we map, so denominations are kept current for those categories and
    nobody else's. Returns ``(denoms_written, missing_categories, error)``.

    The Steam reserve mapping (:data:`PANEL_STEAM_SENTINEL`) is excluded up
    front, the same way ``price_refresh._fetch_nova_offers_cache`` and
    ``cost_lookup._nova_raw_price`` already exclude it: it has no
    catalogue offers to fetch (ADR-0082 §4), so ``get_offers("steam-topup")``
    is a guaranteed 404 every tick — not a mapping gone upstream, just one
    that was never a catalogue category to begin with.
    """
    category_ids = [
        category_id
        for category_id in await svc.mapped_external_product_ids(
            db, supplier_slug=client.slug, kind="game"
        )
        if category_id != PANEL_STEAM_SENTINEL
    ]
    if len(category_ids) > _MAPPED_FETCH_CAP:
        log.warning(
            _ev(client, "mapped_cap_hit"),
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
            log.warning(_ev(client, "mapped_game_gone"), category_id=category_id)
        elif error:
            failures += 1
            log.warning(_ev(client, "mapped_game_failed"), category_id=category_id, error=error)

    error = f"{failures} mapped game(s) failed to refresh offers" if failures else None
    return written, missing, error


async def sync_panel_catalog(db: AsyncSession, *, slug: str) -> CatalogSyncReport:
    """Refresh one panel vendor's half of ``supplier_catalog_cache``.

    Four passes, all best-effort and all independent so one failing does not
    lose the others: the game-category sweep, the mapped games' offers, the
    gift-card category sweep, and the mapped gift-card categories' cards.
    Never raises — the route (``routes.sync_catalog``) and the scheduler tick
    both depend on that. The caller commits.
    """
    client = client_or_none(slug)
    if client is None:
        return CatalogSyncReport(error=f"{slug.upper()}_API_KEY is not configured")

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
                supplier_slug=client.slug,
                kind="game",
                external_id=external_id,
                title=title,
                raw=item,
            )
            games += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        error = f"game sync failed: {exc!s}"[:200]
        log.warning(_ev(client, "games_failed"), error=str(exc))

    try:
        mapped, missing, mapped_error = await _refresh_mapped_game_denoms(db, client)
    except Exception as exc:  # noqa: BLE001 -- best-effort sync, mirrors the games-sweep catch above
        mapped, missing = 0, 0
        mapped_error = f"mapped denom refresh failed: {exc!s}"[:200]
        log.warning(_ev(client, "mapped_denoms_failed"), error=str(exc))
    if mapped_error:
        error = f"{error}; {mapped_error}" if error else mapped_error

    # The gift-card half. Independent of the games sweep above for the same
    # reason the mapped-denomination refresh is: one catalogue failing must
    # not lose the other, and an operator pressing the button wants whatever
    # could be refreshed refreshed.
    try:
        vouchers, voucher_error = await vouchers_sync.sync_giftcard_categories(db, client)
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        vouchers, voucher_error = 0, f"gift-card sync failed: {exc!s}"[:200]
        log.warning(_ev(client, "giftcards_failed"), error=str(exc))
    if voucher_error:
        error = f"{error}; {voucher_error}" if error else voucher_error

    try:
        cards, cards_missing, cards_error = await vouchers_sync.refresh_mapped_giftcards(db, client)
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        cards, cards_missing = 0, 0
        cards_error = f"mapped gift-card refresh failed: {exc!s}"[:200]
        log.warning(_ev(client, "mapped_giftcards_failed"), error=str(exc))
    if cards_error:
        error = f"{error}; {cards_error}" if error else cards_error

    return CatalogSyncReport(
        vouchers=vouchers,
        games=games,
        # One counter for "everything refreshed beyond the sweep", as the
        # report type documents: offers for mapped games, cards for mapped
        # gift-card categories.
        mapped_vouchers=mapped + cards,
        missing_upstream=missing + cards_missing,
        error=error,
    )


async def sync_panel_game_denominations(
    db: AsyncSession, *, slug: str, game_id: str
) -> tuple[int, str | None]:
    """On-demand: pull one category's offers into the cache.

    The one live call this module makes outside the hourly tick, and it
    happens only when an operator explicitly asks for it — see
    ``routes.sync_game_denominations`` for the POST that calls this and why a
    GET handler never may (AGENTS.md §10).
    """
    client = client_or_none(slug)
    if client is None:
        return 0, f"{slug.upper()}_API_KEY is not configured"
    written, missing, error = await _sync_category_denoms(db, client, game_id)
    if missing:
        return 0, f"{slug} has no category {game_id!r}"
    return written, error


async def sync_panel_voucher_denominations(
    db: AsyncSession, *, slug: str, product_id: str
) -> tuple[int, str | None]:
    """On-demand: pull one gift-card category's cards into the cache.

    The voucher twin of :func:`sync_panel_game_denominations`, for the
    operator mapping a category the mapped-only sweep has never touched.
    """
    client = client_or_none(slug)
    if client is None:
        return 0, f"{slug.upper()}_API_KEY is not configured"
    return await vouchers_sync.sync_one_category_cards(db, client, category_id=product_id)


__all__ = [
    "client_or_none",
    "sync_panel_catalog",
    "sync_panel_game_denominations",
    "sync_panel_voucher_denominations",
]
