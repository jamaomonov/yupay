"""Pull a supplier's catalogue into ``supplier_catalog_cache``.

This is where supplier prices enter the system. ``price_refresh`` does not
call G2B — it copies ``supplier_catalog_cache.unit_price`` onto the SKU, which
is what its history rows say (``source="supplier_catalog_cache.unit_price"``).
So the hourly price refresh is only as fresh as the last catalogue sync, and
until this module existed that sync ran solely when an admin pressed a button.

The visible effect was an hourly job reporting ``checked=175, moved=0`` for
days on end while a supplier price had in fact moved: it was faithfully
re-copying a frozen snapshot, and the admin card promising "то же делает
воркер каждый час" was, for the number that matters, untrue.

Extracted from the admin route so the scheduler can run the same code rather
than a second implementation of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.integrations import service as svc

log = get_logger("yupay.integrations.catalog_sync")

#: One page of G2B's product list. Their API pages at 200; see
#: ``sync_g2b_catalog``'s note on why we do not walk every page yet.
_PRODUCT_PAGE_LIMIT = 200


@dataclass(frozen=True)
class CatalogSyncReport:
    """What one sync managed. ``error`` is advisory — a partial sync still counts."""

    vouchers: int = 0
    games: int = 0
    error: str | None = None


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

    return CatalogSyncReport(vouchers=vouchers, games=games, error=error)


__all__ = ["CatalogSyncReport", "sync_g2b_catalog"]
