"""Pull G2B's catalogue into ``supplier_catalog_cache``.

This is where G2B's prices enter the system. ``price_refresh`` does not call
G2B — it copies ``supplier_catalog_cache.unit_price`` onto the SKU, which is
what its history rows say (``source="supplier_catalog_cache.unit_price"``).
So the hourly price refresh is only as fresh as the last catalogue sync, and
until this module existed that sync ran solely when an admin pressed a button.

The visible effect was an hourly job reporting ``checked=175, moved=0`` for
days on end while a supplier price had in fact moved: it was faithfully
re-copying a frozen snapshot, and the admin card promising "то же делает
воркер каждый час" was, for the number that matters, untrue.

Split out of what was a single ``catalog_sync.py`` when NOVA and G-Engine
joined the sync (each supplier's shape is different enough that one function
per supplier read better than a branchy shared one, and three suppliers
would have pushed the file past AGENTS.md §6's 400-LOC soft limit). See
``catalog_sync.py`` for the dispatcher and ``catalog_sync_types.py`` for the
shared :class:`CatalogSyncReport`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.catalog_sync_types import CatalogSyncReport

log = get_logger("yupay.integrations.catalog_sync.g2b")

#: One page of G2B's product list, which the client's docstring puts at
#: ~12 800 rows. This sweep is for the admin picker — something to browse and
#: search when choosing a product to map. What we actually *price* is refreshed
#: by id in ``_refresh_mapped_vouchers``, so nothing depends on page one.
_PRODUCT_PAGE_LIMIT = 200

#: Ceiling on the by-id refresh, so a data mistake cannot turn one tick into
#: thousands of supplier calls. Production maps eight voucher products.
_MAPPED_FETCH_CAP = 200


async def _refresh_mapped_vouchers(db: AsyncSession) -> tuple[int, int, str | None]:
    """Re-read every voucher product an active mapping points at.

    The page sweep fetches page one — 200 rows of a catalogue the client's own
    docstring puts at ~12 800 — so whether a mapped product gets refreshed came
    down to where it happened to sort. Walking all 64 pages hourly to keep a
    handful of rows current is the wrong trade: we only ever price the products
    we map, and there are eight of them.

    Games do not need this. ``refresh_sku_cost_for_mapping`` calls
    ``games_catalogue`` live for those; only vouchers read the cache.

    Returns ``(refreshed, missing_upstream, error)``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return 0, 0, None

    product_ids = await svc.mapped_external_product_ids(db, supplier_slug="g2b", kind="voucher")
    if len(product_ids) > _MAPPED_FETCH_CAP:
        # Loud rather than silently truncated: a cap that trims without saying
        # so reads as "everything is current" when it is not.
        log.warning(
            "integrations.g2b.sync.mapped_cap_hit",
            wanted=len(product_ids),
            cap=_MAPPED_FETCH_CAP,
        )
        product_ids = product_ids[:_MAPPED_FETCH_CAP]

    client = fulfiller._client()
    refreshed = 0
    missing = 0
    failures = 0
    for product_id in product_ids:
        try:
            item = await client.fetch_product(product_id)
        except Exception as exc:  # noqa: BLE001 -- one bad product must not lose the rest
            failures += 1
            log.warning(
                "integrations.g2b.sync.mapped_product_failed",
                product_id=product_id,
                error=str(exc),
            )
            continue
        if item is None:
            # Withdrawn upstream. The cached row stays: a mapping still points
            # at it, and dropping the price silently would be worse than
            # holding the last known one while somebody looks.
            missing += 1
            log.warning("integrations.g2b.sync.mapped_product_gone", product_id=product_id)
            continue
        title = str(item.get("title") or item.get("name") or product_id)[:255]
        await svc.upsert_catalog_entry(
            db,
            supplier_slug="g2b",
            kind="voucher",
            external_id=product_id,
            title=title,
            raw=item,
        )
        refreshed += 1

    error = f"{failures} mapped voucher(s) failed to refresh" if failures else None
    return refreshed, missing, error


async def sync_g2b_catalog(db: AsyncSession) -> CatalogSyncReport:
    """Refresh the G2B half of ``supplier_catalog_cache``.

    Best-effort by design: a supplier hiccup on one half must not lose the
    other, and the caller — an admin route or the scheduler — wants a report
    rather than an exception. The caller commits.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return CatalogSyncReport(error="G2B_API_KEY is not configured")

    client = fulfiller._client()
    vouchers = 0
    games = 0
    error: str | None = None

    try:
        products = await client.fetch_products(page=1, limit=_PRODUCT_PAGE_LIMIT)
        for item in products:
            external_id = str(item.get("id") or item.get("product_id") or "").strip()
            if not external_id:
                continue
            title = str(item.get("title") or item.get("name") or external_id)[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="g2b",
                kind="voucher",
                external_id=external_id,
                title=title,
                raw=item,
            )
            vouchers += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        error = f"voucher sync failed: {exc!s}"[:200]
        log.warning("integrations.g2b.sync.voucher_failed", error=str(exc))

    try:
        games_payload = await client.fetch_games()
        for item in games_payload:
            external_id = str(item.get("code") or item.get("id") or "").strip()
            if not external_id:
                continue
            title = str(item.get("name") or external_id)[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="g2b",
                kind="game",
                external_id=external_id,
                title=title,
                raw=item,
            )
            games += 1
    except Exception as exc:  # noqa: BLE001
        err = f"game sync failed: {exc!s}"[:200]
        error = f"{error}; {err}" if error else err
        log.warning("integrations.g2b.sync.games_failed", error=str(exc))

    # The part that decides what customers pay. Done after the sweep so a
    # mapped product on page seven still ends up current.
    mapped, missing, mapped_error = await _refresh_mapped_vouchers(db)
    if mapped_error:
        error = f"{error}; {mapped_error}" if error else mapped_error

    return CatalogSyncReport(
        vouchers=vouchers,
        games=games,
        mapped_vouchers=mapped,
        missing_upstream=missing,
        error=error,
    )


__all__ = ["sync_g2b_catalog"]
