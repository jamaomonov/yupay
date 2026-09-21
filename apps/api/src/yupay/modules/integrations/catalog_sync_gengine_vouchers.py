"""The shop (gift-card) half of G-Engine's catalogue sync.

``catalog_sync_gengine`` deliberately left this out and said so:

    G-Engine's *shop* catalogue (``list_shop_products``/
    ``list_shop_denominations`` — fixed-price gift codes and keys) is
    intentionally out of scope here … Left for a follow-up if an operator
    hits the same manual-id problem mapping a shop product.

An operator hit it: «у g engine постоянно каталог не синхронизирован», and
the brand-comparison screen showed no G-Engine price for any voucher SKU,
because nothing had ever written one. Four Standoff 2 SKUs and five Roblox
rungs are mapped to shop products today.

Two levels, same as everywhere else in this package:

* ``GET /shop/products`` — one ``voucher`` row per product, one or two
  pages, swept whole;
* ``GET /shop/denominations/{id}`` — ``voucher_denom`` rows, and **only** for
  products an active mapping points at, because this one *is* a call per
  product (unlike ``/recharge/services``, which embeds its denominations).

Mind the namespace trap: shop product ids and recharge service ids are
different sequences that collide. Shop product ``9`` is "Roblox Global";
recharge service ``9`` is Delta Force. They are told apart by ``kind``, which
is why the shop rows had to be ``voucher``/``voucher_denom`` (migration 0086)
and could not reuse ``game``/``game_denom``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.gengine_client import MAX_PAGE, GEngineClient
from yupay.modules.integrations import service as svc

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.integrations.catalog_sync.gengine_vouchers")

#: Ceiling on the per-product denomination refresh, mirroring the games
#: half's two-page budget: a data mistake must not turn one tick into
#: hundreds of ``/shop/denominations`` calls.
_MAPPED_FETCH_CAP = 100


async def list_all_shop_products(client: GEngineClient) -> tuple[list[dict[str, Any]], bool]:
    """Walk up to two pages of ``GET /shop/products``.

    Returns ``(items, truncated)``. ``truncated`` is ``True`` only when the
    second page also came back full — the same contract, and the same
    "one or two calls" budget, as the recharge sweep's own walker.
    """
    items = await client.list_shop_products(limit=MAX_PAGE, offset=0)
    if len(items) < MAX_PAGE:
        return items, False
    page_two = await client.list_shop_products(limit=MAX_PAGE, offset=MAX_PAGE)
    items = items + page_two
    truncated = len(page_two) >= MAX_PAGE
    if truncated:
        log.warning("integrations.gengine.sync.shop_page_limit_hit", collected=len(items))
    return items, truncated


async def _write_shop_denoms(
    db: AsyncSession, client: GEngineClient, product_id: str
) -> tuple[int, str | None]:
    """Write one shop product's denominations as ``voucher_denom`` rows.

    One network call, unlike the recharge half — G-Engine's shop list does
    not embed its ladder.
    """
    try:
        rows = await client.list_shop_denominations(int(product_id))
    except Exception as exc:  # noqa: BLE001 -- one product must not lose the sweep
        return 0, f"{product_id}: {exc!s}"[:200]

    written = 0
    seen: set[str] = set()
    try:
        for denom in rows:
            denom_id = str(denom.get("id") or "").strip()
            if not denom_id:
                continue
            seen.add(denom_id)
            price = denom.get("price")
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="gengine",
                kind="voucher_denom",
                external_id=denom_id,
                title=str(denom.get("name") or denom_id)[:255],
                raw=denom,
                parent_external_id=product_id,
                price_usdt=Decimal(str(price)) if price is not None else None,
            )
            written += 1
        # An empty ``seen`` prunes nothing, by ``prune_catalog_denoms``'s own
        # rule — a product that answered with an empty ladder keeps its cache
        # rather than reading as a delisting.
        await svc.prune_catalog_denoms(
            db, supplier_slug="gengine", parent_external_id=product_id, keep=seen
        )
    except Exception as exc:  # noqa: BLE001 -- a malformed denomination must not raise past here
        return written, f"{product_id}: malformed denomination: {exc!s}"[:200]
    return written, None


async def sync_shop_catalog(db: AsyncSession, client: GEngineClient) -> tuple[int, int, str | None]:
    """Sweep shop products, then refresh the mapped ones' denominations.

    Args:
        db: Session. The caller commits.
        client: A configured G-Engine client.

    Returns:
        ``(products_written, denoms_written, error)``. Never raises: the
        caller (``sync_gengine_catalog``) promises the route and the
        scheduler that much.
    """
    products = 0
    error: str | None = None
    try:
        rows, _truncated = await list_all_shop_products(client)
        for item in rows:
            external_id = str(item.get("id") or "").strip()
            if not external_id:
                continue
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="gengine",
                kind="voucher",
                external_id=external_id,
                title=str(item.get("name") or external_id)[:255],
                raw=item,
            )
            products += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        log.warning("integrations.gengine.sync.shop_failed", error=str(exc))
        error = f"shop sync failed: {exc!s}"[:200]

    denoms, denom_error = await refresh_mapped_shop_denoms(db, client)
    if denom_error:
        error = f"{error}; {denom_error}" if error else denom_error
    return products, denoms, error


async def refresh_mapped_shop_denoms(
    db: AsyncSession, client: GEngineClient
) -> tuple[int, str | None]:
    """Re-read denominations for every mapped G-Engine shop product."""
    try:
        product_ids = await svc.mapped_external_product_ids(
            db, supplier_slug="gengine", kind="voucher"
        )
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        return 0, f"mapped shop lookup failed: {exc!s}"[:200]

    if len(product_ids) > _MAPPED_FETCH_CAP:
        log.warning(
            "integrations.gengine.sync.mapped_shop_cap_hit",
            wanted=len(product_ids),
            cap=_MAPPED_FETCH_CAP,
        )
        product_ids = product_ids[:_MAPPED_FETCH_CAP]

    written = 0
    failures: list[str] = []
    for product_id in product_ids:
        # A product id that is not an integer is a mapping typo, not a
        # supplier problem: ``list_shop_denominations`` takes an int. Skip it
        # loudly rather than letting ``int()`` raise through the sweep.
        if not product_id.isdigit():
            failures.append(f"{product_id}: not a numeric shop product id")
            continue
        count, error = await _write_shop_denoms(db, client, product_id)
        written += count
        if error:
            failures.append(error)
            log.warning("integrations.gengine.sync.mapped_shop_failed", error=error)

    return written, ("; ".join(failures)[:200] if failures else None)


async def sync_one_shop_product_denoms(
    db: AsyncSession, client: GEngineClient, *, product_id: str
) -> tuple[int, str | None]:
    """On-demand: pull one shop product's denominations into the cache."""
    if not product_id.isdigit():
        return 0, f"{product_id!r} is not a numeric G-Engine shop product id"
    return await _write_shop_denoms(db, client, product_id)


__all__ = [
    "list_all_shop_products",
    "refresh_mapped_shop_denoms",
    "sync_one_shop_product_denoms",
    "sync_shop_catalog",
]
