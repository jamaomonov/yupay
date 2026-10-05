"""Alert when a SKU's cost has not been refreshed from its supplier in hours.

The hourly refresh rewrites ``Sku.cost_usdt`` from the routed supplier and
``set_sku_cost_usdt`` stamps ``cost_synced_at`` on every write, moved or not.
A supplier that stops answering — expired key, moved catalogue endpoint, an
hour of 429s — leaves the old cost in place and every retail and B2B price
derived from it, and until this module nothing noticed: the refresh counts
``errors`` per tick and alerts only on big *moves*, so "no move because no
answer" looked exactly like "no move because stable".

A SKU is stale when it is active, fixed-price, has a cost, has an active
mapping to a supplier whose prices are collected (``PRICE_COLLECTION_SUPPORTED_
SUPPLIERS``), is not pinned to the warehouse or the manual queue by a sourcing
rule (nor forced to a supplier without a price feed), and ``cost_synced_at``
is older than ``settings.cost_stale_after_hours`` or NULL. The mapping test is deliberately coarse — resolving the route in SQL
is not possible, and a SKU pinned to inventory with a live mapping would
otherwise alert forever, so those two rule modes are excluded by name.

Pure query in :func:`find_stale`, message in :func:`format_alert`; the send
and the six-hour dedupe live in :func:`maybe_alert`.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.cost_refresh import PRICE_COLLECTION_SUPPORTED_SUPPLIERS
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.notifications import api as notifications
from yupay.modules.sourcing.models import SkuSourcingRule

log = get_logger(__name__)

_DEDUPE_KEY = "alert:cost_stale"
_DEDUPE_TTL = 6 * 3600
_TOP = 8
_UNROUTED_MODES = ("force_inventory", "manual")


@dataclass(frozen=True)
class StaleRow:
    """One SKU whose cost has not been confirmed by a supplier lately."""

    brand_slug: str
    sku_code: str
    suppliers: str
    synced_at: datetime | None


@dataclass(frozen=True)
class Staleness:
    """What :func:`find_stale` found: the oldest rows and the full count."""

    rows: list[StaleRow]
    total: int
    by_supplier: dict[str, int]


async def find_stale(db: AsyncSession, *, max_age: timedelta, top: int = _TOP) -> Staleness:
    """Active fixed-price SKUs whose cost is older than ``max_age``.

    Args:
        db: Session to read with.
        max_age: How long without a supplier answer counts as stale.
        top: How many rows to keep, oldest first.

    Returns:
        The staleness, with the full count, a per-supplier breakdown (a SKU
        mapped to two suppliers counts under each — the point is "who is not
        answering") and the ``top`` oldest rows.
    """
    cutoff = now() - max_age
    priced = (
        select(SkuSupplierMapping.sku_id)
        .where(
            SkuSupplierMapping.sku_id == Sku.id,
            SkuSupplierMapping.is_active.is_(True),
            SkuSupplierMapping.supplier_slug.in_(PRICE_COLLECTION_SUPPORTED_SUPPLIERS),
        )
        .exists()
    )
    # Pinned somewhere no price feed exists: the warehouse, the manual queue
    # (either as ``mode="manual"`` or as ``force_supplier`` with slug
    # ``manual`` — the first prod tick alerted on exactly that), or forced to
    # a supplier whose prices are not collected.
    pinned = exists(
        select(SkuSourcingRule.sku_id).where(
            SkuSourcingRule.sku_id == Sku.id,
            or_(
                SkuSourcingRule.mode.in_(_UNROUTED_MODES),
                and_(
                    SkuSourcingRule.mode == "force_supplier",
                    or_(
                        SkuSourcingRule.supplier_slug.is_(None),
                        SkuSourcingRule.supplier_slug.notin_(PRICE_COLLECTION_SUPPORTED_SUPPLIERS),
                    ),
                ),
            ),
        )
    )
    suppliers = (
        select(func.string_agg(SkuSupplierMapping.supplier_slug, ","))
        .where(
            SkuSupplierMapping.sku_id == Sku.id,
            SkuSupplierMapping.is_active.is_(True),
            SkuSupplierMapping.supplier_slug.in_(PRICE_COLLECTION_SUPPORTED_SUPPLIERS),
        )
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Brand.slug, Sku.sku_code, suppliers, Sku.cost_synced_at)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                Sku.active.is_(True),
                Sku.variable_amount.is_(False),
                Sku.cost_usdt.isnot(None),
                or_(Sku.cost_synced_at.is_(None), Sku.cost_synced_at < cutoff),
                priced,
                ~pinned,
            )
            .order_by(Sku.cost_synced_at.asc().nulls_first())
        )
    ).all()
    by_supplier: dict[str, int] = {}
    for _brand, _code, slugs, _at in rows:
        for slug in (slugs or "").split(","):
            if slug:
                by_supplier[slug] = by_supplier.get(slug, 0) + 1
    return Staleness(
        rows=[
            StaleRow(brand_slug=b, sku_code=c, suppliers=s or "", synced_at=at)
            for b, c, s, at in rows[:top]
        ],
        total=len(rows),
        by_supplier=by_supplier,
    )


def _age(synced_at: datetime | None) -> str:
    if synced_at is None:
        return "никогда"
    hours = int((now() - synced_at).total_seconds() // 3600)
    return f"{hours} ч назад" if hours < 48 else f"{hours // 24} дн назад"


def format_alert(stale: Staleness, *, max_age: timedelta) -> str:
    """The Telegram message, HTML: who is not answering, then the oldest SKUs."""
    hours = int(max_age.total_seconds() // 3600)
    parts = [
        "<b>⏳ Себестоимость устарела</b>",
        f"{stale.total} SKU без ответа поставщика дольше {hours} ч. Цены на полке и для "
        "реселлеров считаются от старой закупки.",
    ]
    if stale.by_supplier:
        parts.append(
            "По поставщикам: "
            + ", ".join(
                f"{html.escape(s)} — {n}"
                for s, n in sorted(stale.by_supplier.items(), key=lambda kv: -kv[1])
            )
        )
    parts.extend(
        f"• <code>{html.escape(r.brand_slug)}/{html.escape(r.sku_code)}</code> "
        f"({html.escape(r.suppliers)}) — {_age(r.synced_at)}"
        for r in stale.rows
    )
    parts.append("Проверь ключ и каталог поставщика; затем «Обновить цены» в Интеграциях.")
    return "\n".join(parts)


async def maybe_alert() -> bool:
    """Send the staleness alert if anything is stale and none went out in 6 h.

    Called from the hourly refresh after the prices are written, so a
    supplier that answered this tick is fresh by the time this runs. Disabled
    by ``cost_stale_after_hours <= 0``. Never raises.

    Returns:
        Whether a message was sent.
    """
    hours = int(get_settings().cost_stale_after_hours)
    if hours <= 0:
        return False
    from yupay.modules.fulfillment.service import _set_redis_dedupe

    max_age = timedelta(hours=hours)
    try:
        async with get_session_factory()() as db:
            stale = await find_stale(db, max_age=max_age)
    except Exception as exc:  # noqa: BLE001 -- an alert must not break the refresh
        log.warning("integrations.cost_staleness.failed", error=str(exc))
        return False
    if stale.total == 0:
        return False
    log.warning(
        "integrations.cost_staleness.stale",
        total=stale.total,
        by_supplier=stale.by_supplier,
    )
    if await _set_redis_dedupe(_DEDUPE_KEY, ttl_seconds=_DEDUPE_TTL):
        return False
    return await notifications.send_admin_alert(
        format_alert(stale, max_age=max_age), kind="cost_stale"
    )


__all__ = ["StaleRow", "Staleness", "find_stale", "format_alert", "maybe_alert"]
