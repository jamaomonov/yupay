"""Ops tab analytics: payments, fulfilment, inventory, supplier cost movements.

``_LOW_STOCK_THRESHOLD``, ``_STUCK_PAYMENT_AFTER`` and ``_count_stuck_payments``
are canonical in ``yupay.modules.stats.service`` and imported from there. That
import is deliberately function-local (not module-level) here: when this
package is imported before ``service`` (e.g. ``import
yupay.modules.stats.analytics`` on its own), a module-level import would
recurse into ``service``'s own late import of ``build_ops_analytics`` from
this package before this module has finished being defined — a circular
``ImportError``. Deferring the import to call time sidesteps that; by the
time these functions actually run, both modules are fully initialised
regardless of which one was imported first.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.integrations.models import SupplierPriceHistory
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment, PaymentWebhook
from yupay.modules.stats.schemas import (
    AnalyticsRange,
    CostChangeOut,
    LowStockOut,
    OpsAnalyticsOut,
    ProviderStatOut,
    SupplierStatOut,
    range_to_days,
)


async def build_ops_analytics(db: AsyncSession, *, r: AnalyticsRange) -> OpsAnalyticsOut:
    """Ops tab: payments, fulfilment, inventory, supplier cost movements."""
    # Local import — see module docstring for why this can't be module-level.
    from yupay.modules.stats.service import _STUCK_PAYMENT_AFTER, _count_stuck_payments

    moment = now()
    since = moment - timedelta(days=range_to_days(r))

    payments = await _payment_stats(db, since)
    stuck_pending = await _count_stuck_payments(db, moment - _STUCK_PAYMENT_AFTER)
    webhook_unhealthy = await _webhook_unhealthy(db, since)
    fulfillment = await _fulfillment_stats(db, since)
    stuck_tasks = await _stuck_tasks(db, moment)
    low_stock = await _low_stock(db)
    expiring_soon = await _expiring_soon(db, moment)
    supplier_cost = await _supplier_cost_changes(db, since)

    return OpsAnalyticsOut(
        generated_at=moment,
        range=r,
        payments=payments,
        stuck_pending=stuck_pending,
        webhook_unhealthy=webhook_unhealthy,
        fulfillment=fulfillment,
        stuck_tasks=stuck_tasks,
        low_stock=low_stock,
        expiring_soon=expiring_soon,
        supplier_cost=supplier_cost,
    )


async def _payment_stats(db: AsyncSession, since: datetime) -> list[ProviderStatOut]:
    """Per-provider volume, in USD — which is not what `Payment.amount` holds.

    `Payment.amount` is the charge in the payment's **own** currency: so'm for
    Click, Payme and Uzum, USDT for crypto. Summing it produced a figure
    labelled `volume_usd` and rendered with a `$`, so the admin read
    "$35 181 403" for what was 35 million so'm — and the providers were not
    comparable with each other either, since the column silently mixed units.

    The order already carries the same charge converted at its own frozen FX
    snapshot, so the join is the answer rather than a rate lookup here.
    `order_id` is NOT NULL, so the inner join changes no count.
    """
    stmt = (
        select(
            Payment.provider,
            func.count(),
            func.coalesce(func.sum(Order.total_usd).filter(Payment.status == "succeeded"), 0),
            func.count().filter(Payment.status == "succeeded"),
        )
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.created_at >= since)
        .group_by(Payment.provider)
        .order_by(func.count().desc())
    )
    out: list[ProviderStatOut] = []
    for provider, total_raw, vol, ok in (await db.execute(stmt)).all():
        total = int(total_raw or 0)
        rate = round(int(ok or 0) / total * 100, 2) if total else 0.0
        out.append(
            ProviderStatOut(
                provider=provider,
                count=total,
                volume_usd=Decimal(str(vol or 0)),
                success_rate_pct=rate,
            )
        )
    return out


async def _webhook_unhealthy(db: AsyncSession, since: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(PaymentWebhook)
        .where(
            PaymentWebhook.received_at >= since,
            or_(PaymentWebhook.signature_ok.is_(False), PaymentWebhook.processed_at.is_(None)),
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _fulfillment_stats(db: AsyncSession, since: datetime) -> list[SupplierStatOut]:
    secs = func.extract("epoch", FulfillmentTask.succeeded_at - FulfillmentTask.created_at)
    stmt = (
        select(
            FulfillmentTask.supplier,
            func.count(),
            func.count().filter(FulfillmentTask.status == "succeeded"),
            func.avg(secs).filter(FulfillmentTask.status == "succeeded"),
            func.count().filter(FulfillmentTask.completed_by.isnot(None)),
            func.coalesce(func.avg(FulfillmentTask.attempts_count), 0),
        )
        .where(FulfillmentTask.created_at >= since)
        .group_by(FulfillmentTask.supplier)
        .order_by(func.count().desc())
    )
    out: list[SupplierStatOut] = []
    for supplier, total_raw, ok, avg_sec, manual, avg_att in (await db.execute(stmt)).all():
        total = int(total_raw or 0)
        rate = round(int(ok or 0) / total * 100, 2) if total else 0.0
        out.append(
            SupplierStatOut(
                supplier=supplier,
                total=total,
                success_rate_pct=rate,
                avg_seconds=round(float(avg_sec), 1) if avg_sec is not None else None,
                manual_count=int(manual or 0),
                avg_attempts=round(float(avg_att or 0), 2),
            )
        )
    return out


async def _stuck_tasks(db: AsyncSession, moment: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(FulfillmentTask)
        .where(
            FulfillmentTask.status.in_(("pending", "in_progress")),
            FulfillmentTask.next_attempt_at.isnot(None),
            FulfillmentTask.next_attempt_at < moment,
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _low_stock(db: AsyncSession) -> list[LowStockOut]:
    # Local import — see module docstring for why this can't be module-level.
    from yupay.modules.stats.service import _LOW_STOCK_THRESHOLD

    avail = func.sum(case((InventoryCode.state == "available", 1), else_=0)).label("a")
    stmt = (
        select(Sku.sku_code, avail)
        .select_from(InventoryCode)
        .join(Sku, Sku.id == InventoryCode.sku_id)
        .group_by(Sku.sku_code)
        .having(avail < _LOW_STOCK_THRESHOLD)
        .order_by(avail)
        .limit(20)
    )
    return [
        LowStockOut(sku_code=code, available=int(a or 0))
        for code, a in (await db.execute(stmt)).all()
    ]


async def _expiring_soon(db: AsyncSession, moment: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(InventoryCode)
        .where(
            InventoryCode.state == "available",
            InventoryCode.expires_at.isnot(None),
            InventoryCode.expires_at < moment + timedelta(days=7),
        )
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _supplier_cost_changes(db: AsyncSession, since: datetime) -> list[CostChangeOut]:
    stmt = (
        select(
            Sku.sku_code,
            SupplierPriceHistory.supplier_slug,
            SupplierPriceHistory.cost_usdt,
            SupplierPriceHistory.previous_cost_usdt,
            SupplierPriceHistory.captured_at,
        )
        .select_from(SupplierPriceHistory)
        .join(Sku, Sku.id == SupplierPriceHistory.sku_id)
        .where(SupplierPriceHistory.captured_at >= since)
        .order_by(SupplierPriceHistory.captured_at.desc())
        .limit(20)
    )
    return [
        CostChangeOut(
            sku_code=code,
            supplier_slug=slug,
            cost_usdt=Decimal(str(cost)),
            previous_cost_usdt=Decimal(str(prev)) if prev is not None else None,
            captured_at=cap,
        )
        for code, slug, cost, prev, cap in (await db.execute(stmt)).all()
    ]


__all__ = ["build_ops_analytics"]
