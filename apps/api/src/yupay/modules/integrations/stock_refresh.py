"""Refresh supplier stock for voucher SKUs.

Game top-ups are minted on demand and never run out. Gift cards and vouchers are
real codes in a supplier's warehouse: G2B reports a count per product, and a
large share of its catalogue sits at zero at any moment. Selling one we cannot
deliver costs a manual refund, so the count is pulled on a schedule and checkout
refuses SKUs that have run dry (``orders.service.sku_is_buyable``).

All three voucher suppliers are swept, and they report stock at different levels:

* **G2B** — one count per product (``GET /products/{id}``).
* **G-Engine** — a count per *denomination* (``GET /shop/denominations/{product}``),
  which returns every denomination of a product in one call. Standoff 2 alone is
  four SKUs behind one product id, so the responses are cached per product for
  the length of a run rather than fetched once per SKU.
* **NOVA** — a count per ``card_id`` inside one call for the whole gift-card
  category (``GET /api/v2/giftcards/cards``), so the same per-id caching as
  G-Engine. Added 2026-09-21 with the Roblox cards: until then a NOVA-only
  voucher SKU was untracked, which the catalogue reads as always sellable.

Invoked from the hourly scheduler job
(``apps/scheduler/.../jobs/refresh_voucher_stock.py``).

Read per product id rather than by walking ``GET /products``: the paginated list
is ~12 800 rows, which is 129 requests to find the ten mappings we actually
have. Each mapping is processed in its own transaction so one failure does not
roll back the rest — the same shape as ``price_refresh``.

The count is never exposed to customers; only the derived ``Sku.in_stock``
boolean is. Observed live, "800 Robux Global" moved 423 → 422 between two calls
seconds apart, which is exactly why a number on the page would be a promise we
cannot keep.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.notifications import api as notifications

log = get_logger("yupay.integrations.stock_refresh")


@dataclass(frozen=True)
class StockRefreshReport:
    """Aggregate result returned to whoever triggered the run."""

    checked: int = 0
    updated: int = 0
    went_out_of_stock: int = 0
    errors: int = 0


def normalise_stock(raw: Any) -> int | None:
    """Map G2B's ``stock`` onto our column.

    G2B answers three ways and they mean different things:

    * a non-negative integer — that many codes left
    * ``-1`` — observed on lines that are clearly sellable, so read as "not
      tracked" rather than as a deficit. Stored as NULL, which is what every
      game top-up carries.
    * missing / non-numeric — nothing was said, so claim nothing: NULL.

    Guessing the other way on ``-1`` would silently pull sellable products off
    the storefront, which is the more expensive mistake of the two.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = int(raw)
    return None if value < 0 else value


async def refresh_voucher_stock(
    *,
    client: Any | None = None,
    gengine_client: Any | None = None,
    nova_client: Any | None = None,
) -> StockRefreshReport:
    """Pull stock for every active voucher mapping and persist it.

    Returns a per-run summary. Alerts on the *transition* into out-of-stock
    only — a SKU that has been empty for a week should not re-alert every hour.

    The clients are injectable for tests, mirroring how ``G2bFulfiller`` takes
    one; in production each is borrowed from its registered adapter so
    credentials and retry policy stay in one place. A supplier whose adapter is
    not registered is skipped rather than failing the run — the other one still
    needs sweeping.
    """
    sources: dict[str, Any] = {}
    g2b = client if client is not None else _g2b_client()
    if g2b is not None:
        sources["g2b"] = g2b
    gengine = gengine_client if gengine_client is not None else _gengine_client()
    if gengine is not None:
        sources["gengine"] = gengine
    nova = nova_client if nova_client is not None else _nova_client()
    if nova is not None:
        sources["nova"] = nova
    for slug in ("g2b", "gengine", "nova"):
        if slug not in sources:
            log.info("stock_refresh.supplier_skipped", supplier=slug)
    if not sources:
        # Nothing to ask. Returning before the session keeps the scheduler tick
        # free of a pointless connection when no supplier key is configured.
        return StockRefreshReport()

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    SkuSupplierMapping.sku_id,
                    SkuSupplierMapping.supplier_slug,
                    SkuSupplierMapping.external_product_id,
                    SkuSupplierMapping.external_variant_id,
                ).where(
                    SkuSupplierMapping.supplier_slug.in_(tuple(sources)),
                    SkuSupplierMapping.kind == "voucher",
                    SkuSupplierMapping.is_active.is_(True),
                )
            )
        ).all()
        targets = [
            (str(sku_id), str(supplier), str(product_id), variant_id)
            for sku_id, supplier, product_id, variant_id in rows
        ]

    #: G-Engine answers with every denomination of a product at once, and NOVA
    #: with every card of a category, so one response serves all the SKUs
    #: behind that id. Keyed by supplier as well as id: the two namespaces are
    #: unrelated and a bare `roblox_global` could otherwise collide with a
    #: G-Engine product id.
    denominations: dict[str, dict[str, Any] | None] = {}

    checked = updated = out = errors = 0
    for sku_id, supplier, product_id, variant_id in targets:
        checked += 1
        try:
            new_stock = await _stock_for(
                supplier,
                sources[supplier],
                product_id=product_id,
                variant_id=variant_id,
                cache=denominations,
            )
        except Exception:
            log.exception(
                "stock_refresh.fetch_failed", supplier=supplier, external_product_id=product_id
            )
            errors += 1
            continue

        async with factory() as session:
            sku = (await session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one_or_none()
            if sku is None:
                continue
            was_in_stock = sku.in_stock
            if sku.supplier_stock != new_stock:
                updated += 1
            sku.supplier_stock = new_stock
            sku.supplier_stock_at = datetime.now(UTC)
            now_in_stock = sku.in_stock
            sku_code = sku.sku_code
            await session.commit()

        if was_in_stock and not now_in_stock:
            out += 1
            await _alert_out_of_stock(
                sku_code=sku_code, external_id=variant_id or product_id, supplier=supplier
            )

    log.info(
        "stock_refresh.done", checked=checked, updated=updated, out_of_stock=out, errors=errors
    )
    return StockRefreshReport(
        checked=checked, updated=updated, went_out_of_stock=out, errors=errors
    )


async def _stock_for(
    supplier: str,
    client: Any,
    *,
    product_id: str,
    variant_id: str | None,
    cache: dict[str, dict[str, Any] | None],
) -> int | None:
    """Stock for one mapping, asked of whichever supplier owns it."""
    if supplier == "gengine":
        return await _gengine_stock(
            client, product_id=product_id, variant_id=variant_id, cache=cache
        )
    if supplier == "nova":
        return await _nova_stock(client, category_id=product_id, card_id=variant_id, cache=cache)
    product = await client.fetch_product(product_id)
    # Withdrawn upstream is not "unknown" — it is zero. Leaving it NULL would
    # keep selling a product G2B no longer lists.
    return 0 if product is None else normalise_stock(product.get("stock"))


def _g2b_client() -> Any | None:
    """The G2B read client, or None when the adapter is not registered."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller):
        return None
    return fulfiller.client_for_reads()


def _gengine_client() -> Any | None:
    """The G-Engine read client, or None when the adapter is not registered."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.gengine import GEngineFulfiller

    fulfiller = REGISTRY.get("gengine")
    if not isinstance(fulfiller, GEngineFulfiller) or not fulfiller.available:
        return None
    return fulfiller.client_for_reads()


async def _gengine_stock(
    client: Any,
    *,
    product_id: str,
    variant_id: str | None,
    cache: dict[str, dict[str, Any] | None],
) -> int | None:
    """Stock for one G-Engine denomination.

    A denomination that has vanished from the product reads as zero for the
    same reason a withdrawn G2B product does: it cannot be delivered, and
    leaving it NULL would keep it on the shelf.
    """
    if product_id not in cache:
        rows = await client.list_shop_denominations(int(product_id))
        cache[product_id] = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    by_id = cache[product_id] or {}
    if variant_id is None:
        # No denomination pinned: the whole product is the line, so it is in
        # stock while any of its denominations is.
        counts = [normalise_stock(r.get("stock")) for r in by_id.values()]
        real = [c for c in counts if c is not None]
        return max(real) if real else None
    row = by_id.get(str(variant_id))
    return 0 if row is None else normalise_stock(row.get("stock"))


def _nova_client() -> Any | None:
    """The NOVA read client, or None when the adapter is not registered."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    fulfiller = REGISTRY.get("nova")
    if not isinstance(fulfiller, NovaFulfiller) or not fulfiller.available:
        return None
    return fulfiller.client_for_reads()


async def _nova_stock(
    client: Any,
    *,
    category_id: str,
    card_id: str | None,
    cache: dict[str, dict[str, Any] | None],
) -> int | None:
    """Stock for one NOVA gift-card denomination.

    NOVA reports a count per ``card_id`` inside one call for the whole
    category, so this is G-Engine's shape rather than G2B's — cached per
    category for the length of a run.

    Without this, a NOVA-only SKU carried ``supplier_stock = NULL``, which the
    catalogue reads as "not tracked" and therefore always sellable: a card
    NOVA had run out of stayed on the shelf and clickable, and the order died
    at the supplier. Roblox 2500 ships with nine in stock, so that was not a
    theoretical window.
    """
    key = f"nova:{category_id}"
    if key not in cache:
        rows = await client.list_giftcard_cards(category_id)
        cache[key] = {str(row.get("card_id")): row for row in rows if isinstance(row, dict)}
    by_id = cache[key] or {}
    if card_id is None:
        counts = [normalise_stock(r.get("stock")) for r in by_id.values()]
        real = [c for c in counts if c is not None]
        return max(real) if real else None
    row = by_id.get(str(card_id))
    # A denomination that has vanished from the category reads as zero, for
    # the same reason a withdrawn G2B product does: it cannot be delivered.
    return 0 if row is None else normalise_stock(row.get("stock"))


async def _alert_out_of_stock(*, sku_code: str, external_id: str, supplier: str = "g2b") -> None:
    """Tell the operator a line just emptied.

    Only on the transition. A SKU that has been out for a week is a known state,
    and a channel that repeats itself hourly stops being read.
    """
    text = (
        "<b>Ваучер закончился</b>\n"
        f"SKU: <code>{html.escape(sku_code)}</code>\n"
        f"{html.escape(supplier)}: <code>{html.escape(str(external_id))}</code>\n"
        "Позиция скрыта с витрины до появления кодов у поставщика."
    )
    await notifications.send_admin_alert(text, kind="voucher_out_of_stock")
