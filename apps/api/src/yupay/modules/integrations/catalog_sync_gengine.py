"""Pull G-Engine's recharge (top-up) catalogue into ``supplier_catalog_cache``.

G-Engine's ``GET /recharge/services`` is unusual among the three suppliers
this package syncs: **it returns each service's denominations inline**
(``item["denominations"]``) — there is no separate per-game call the way
NOVA's ``get_offers`` or G2B's ``games_catalogue`` are. That changes the
shape of the "don't sweep denominations wholesale" rule from Task 2 rather
than lifting it: the data is already in hand at zero extra HTTP cost, so
writing every service's denominations to the cache would cost nothing
upstream — but it would still leave the cache full of rows for games nobody
has mapped, which is the actual problem the rule guards against (a picker
full of stale rows nobody asked for, and a cache that never stops growing).
So the restriction is kept: only a mapped service's denominations are
written during the full sweep, filtered out of the response already in
memory rather than fetched again.

The on-demand single-game sync (:func:`sync_gengine_game_denominations`)
still has to ask upstream, because it may be syncing a game the mapped-only
sweep above has never written — G-Engine has no "one service" endpoint, so it
re-walks the (small) services list and picks the match.

G-Engine's *shop* catalogue (``list_shop_products``/``list_shop_denominations``
— fixed-price gift codes and keys) is intentionally out of scope here: the
owner's complaint and this task's contract are both about the game/top-up
service+denomination pair (``service_id``/``denomination_id``, the "ID
сервиса"/"ID номинала" fields), and G-Engine's shop catalogue would need a
fourth cache kind (``game_denom`` doesn't fit a shop denomination
semantically) that nothing here asked for. Left for a follow-up if an
operator hits the same manual-id problem mapping a shop product.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.gengine_client import MAX_PAGE, GEngineClient
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.catalog_sync_types import CatalogSyncReport

log = get_logger("yupay.integrations.catalog_sync.gengine")


def _gengine_client_or_none() -> GEngineClient | None:
    """The registered G-Engine client iff ``GENGINE_API_KEY`` is configured."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.gengine import GEngineFulfiller

    fulfiller = REGISTRY.get("gengine")
    if isinstance(fulfiller, GEngineFulfiller) and fulfiller.available:
        return fulfiller._client()
    return None


async def _list_all_services(client: GEngineClient) -> list[dict[str, Any]]:
    """Walk up to two pages of ``GET /recharge/services``.

    G-Engine's own catalogue "overlaps ours almost exactly" (see
    ``fulfillment/suppliers/gengine.py``) — a handful of titles — so one page
    at the server's own cap (:data:`MAX_PAGE` = 100) covers it today. A
    second page is fetched only if the first came back full, to stay inside
    the "one or two calls" budget a full sync is meant to cost.
    """
    items = await client.list_recharge_services(limit=MAX_PAGE, offset=0)
    if len(items) == MAX_PAGE:
        items = items + await client.list_recharge_services(limit=MAX_PAGE, offset=MAX_PAGE)
    return items


async def _write_denoms(db: AsyncSession, service: dict[str, Any]) -> int:
    """Write one already-fetched service's embedded denominations as
    ``game_denom`` rows. No network call — the data is already in hand."""
    service_id = str(service.get("id") or "").strip()
    if not service_id:
        return 0
    written = 0
    for denom in service.get("denominations") or []:
        denom_id = str(denom.get("id") or "").strip()
        if not denom_id:
            continue
        title = str(denom.get("name") or denom_id)[:255]
        price = denom.get("price")
        await svc.upsert_catalog_entry(
            db,
            supplier_slug="gengine",
            kind="game_denom",
            external_id=denom_id,
            title=title,
            raw=denom,
            parent_external_id=service_id,
            price_usdt=Decimal(str(price)) if price is not None else None,
        )
        written += 1
    return written


async def sync_gengine_catalog(db: AsyncSession) -> CatalogSyncReport:
    """Refresh the G-Engine half of ``supplier_catalog_cache``.

    One (occasionally two) calls to ``GET /recharge/services`` write every
    service as a ``game`` row; denominations are written too, but only for
    services an active mapping already points at (see module docstring) —
    straight out of the same response, no extra call. The caller commits.
    """
    client = _gengine_client_or_none()
    if client is None:
        return CatalogSyncReport(error="GENGINE_API_KEY is not configured")

    mapped_ids = set(
        await svc.mapped_external_product_ids(db, supplier_slug="gengine", kind="game")
    )
    games = 0
    mapped_denoms = 0
    seen_ids: set[str] = set()
    error: str | None = None
    try:
        services = await _list_all_services(client)
        for item in services:
            external_id = str(item.get("id") or "").strip()
            if not external_id:
                continue
            seen_ids.add(external_id)
            title = str(item.get("name") or external_id)[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="gengine",
                kind="game",
                external_id=external_id,
                title=title,
                raw=item,
            )
            games += 1
            if external_id in mapped_ids:
                mapped_denoms += await _write_denoms(db, item)
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        error = f"game sync failed: {exc!s}"[:200]
        log.warning("integrations.gengine.sync.games_failed", error=str(exc))

    # Only trustworthy when the sweep actually completed — a total outage
    # must not read as "every mapped game just got pulled by the supplier".
    missing_upstream = 0 if error else len(mapped_ids - seen_ids)

    return CatalogSyncReport(
        games=games,
        mapped_vouchers=mapped_denoms,
        missing_upstream=missing_upstream,
        error=error,
    )


async def sync_gengine_game_denominations(
    db: AsyncSession, *, game_id: str
) -> tuple[int, str | None]:
    """On-demand: pull one G-Engine service's denominations into the cache.

    G-Engine has no per-service endpoint, so this re-walks the (small)
    services list and picks the match — still just the "one or two calls"
    :func:`_list_all_services` is built for. The one live G-Engine call this
    module makes outside the hourly tick; see
    ``routes.sync_game_denominations`` for why it is a POST (AGENTS.md §10).
    """
    client = _gengine_client_or_none()
    if client is None:
        return 0, "GENGINE_API_KEY is not configured"
    try:
        services = await _list_all_services(client)
    except Exception as exc:  # noqa: BLE001 -- best-effort, mirrors the full sweep
        return 0, str(exc)[:200]
    match = next((s for s in services if str(s.get("id") or "").strip() == game_id), None)
    if match is None:
        return 0, f"g-engine has no recharge service {game_id!r}"
    return await _write_denoms(db, match), None


__all__ = ["sync_gengine_catalog", "sync_gengine_game_denominations"]
