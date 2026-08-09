"""Refresh supplier stock for voucher SKUs.

Game top-ups are minted on demand and never run out. Gift cards and vouchers are
real codes in a supplier's warehouse: G2B reports a count per product, and a
large share of its catalogue sits at zero at any moment. Selling one we cannot
deliver costs a manual refund, so the count is pulled on a schedule and checkout
refuses SKUs that have run dry (``orders.service._sku_is_buyable``).

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


async def refresh_voucher_stock() -> StockRefreshReport:
    """Pull stock for every active voucher mapping and persist it.

    Returns a per-run summary. Alerts on the *transition* into out-of-stock
    only — a SKU that has been empty for a week should not re-alert every hour.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller):
        log.info("stock_refresh.skipped", reason="g2b adapter not registered")
        return StockRefreshReport()

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(SkuSupplierMapping.sku_id, SkuSupplierMapping.external_product_id).where(
                    SkuSupplierMapping.supplier_slug == "g2b",
                    SkuSupplierMapping.kind == "voucher",
                    SkuSupplierMapping.is_active.is_(True),
                )
            )
        ).all()
        targets = [(str(sku_id), str(external_id)) for sku_id, external_id in rows]

    checked = updated = out = errors = 0
    client = fulfiller.client_for_reads()
    for sku_id, external_id in targets:
        checked += 1
        try:
            product = await client.fetch_product(external_id)
        except Exception:
            log.exception("stock_refresh.fetch_failed", external_product_id=external_id)
            errors += 1
            continue

        # Withdrawn upstream is not "unknown" — it is zero. Leaving it NULL
        # would keep selling a product G2B no longer lists.
        new_stock = 0 if product is None else normalise_stock(product.get("stock"))

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
            await _alert_out_of_stock(sku_code=sku_code, external_id=external_id)

    log.info(
        "stock_refresh.done", checked=checked, updated=updated, out_of_stock=out, errors=errors
    )
    return StockRefreshReport(
        checked=checked, updated=updated, went_out_of_stock=out, errors=errors
    )


async def _alert_out_of_stock(*, sku_code: str, external_id: str) -> None:
    """Tell the operator a line just emptied.

    Only on the transition. A SKU that has been out for a week is a known state,
    and a channel that repeats itself hourly stops being read.
    """
    text = (
        "<b>Ваучер закончился</b>\n"
        f"SKU: <code>{html.escape(sku_code)}</code>\n"
        f"G2B product: <code>{html.escape(str(external_id))}</code>\n"
        "Позиция скрыта с витрины до появления кодов у поставщика."
    )
    await notifications.send_admin_alert(text, kind="voucher_out_of_stock")
