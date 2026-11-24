"""Mappings whose price nobody could fetch for a while (ADR-0108).

The question behind «при переключении часто нет цены»: which supplier mappings
are dead — a category FazerCards removed, an offer gone from a catalogue — and
which of them is a SKU's live route, where orders fail rather than merely
miss a comparison. Read from ``supplier_price_state``, which every hourly
price refresh writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now


class PriceFailureOut(BaseModel):
    """One mapping with no good price for ``hours`` or more."""

    sku_id: str
    sku_code: str | None = None
    label: str | None = None
    supplier_slug: str
    #: The SKU routes to this supplier now: its orders go here.
    routed: bool
    checked_at: datetime | None
    failed_at: datetime
    last_error: str | None


class PriceFailureGroupOut(BaseModel):
    supplier_slug: str
    error: str
    count: int


class PriceFailureReportOut(BaseModel):
    total: int
    routed: int
    groups: list[PriceFailureGroupOut]
    items: list[PriceFailureOut]


_SQL = text(
    """
    SELECT s.sku_id, s.supplier_slug, s.checked_at, s.failed_at, s.last_error,
           (r.mode = 'force_supplier' AND r.supplier_slug = s.supplier_slug) AS routed
    FROM supplier_price_state s
    JOIN sku_supplier_mapping m
      ON m.sku_id = s.sku_id AND m.supplier_slug = s.supplier_slug AND m.is_active
    LEFT JOIN sku_sourcing_rules r ON r.sku_id = s.sku_id
    WHERE s.failed_at IS NOT NULL
      AND (s.checked_at IS NULL OR s.checked_at < :before)
      AND s.failed_at > COALESCE(s.checked_at, '-infinity'::timestamptz)
      AND (CAST(:supplier AS text) IS NULL OR s.supplier_slug = :supplier)
    ORDER BY routed DESC NULLS LAST, s.supplier_slug, s.failed_at DESC
    """
)


async def price_failures(
    db: AsyncSession, *, hours: int, supplier: str | None, limit: int
) -> PriceFailureReportOut:
    """Dead-looking mappings, routed ones first, grouped by supplier and error."""
    from yupay.modules.catalog.admin_service import sku_labels_for

    rows = (
        await db.execute(_SQL, {"before": now() - timedelta(hours=hours), "supplier": supplier})
    ).all()
    groups: dict[tuple[str, str], int] = {}
    for _sku, slug, _checked, _failed, error, _routed in rows:
        key = (slug, _error_kind(error))
        groups[key] = groups.get(key, 0) + 1
    shown = rows[:limit]
    labels = await sku_labels_for(db, [str(r[0]) for r in shown])
    items: list[PriceFailureOut] = []
    for sku, slug, checked, failed, error, routed in shown:
        label: Any = labels.get(str(sku))
        items.append(
            PriceFailureOut(
                sku_id=str(sku),
                sku_code=label.sku_code if label else None,
                label=" · ".join(p for p in (label.brand_name, label.denomination) if p)
                if label
                else None,
                supplier_slug=slug,
                routed=bool(routed),
                checked_at=checked,
                failed_at=failed,
                last_error=error,
            )
        )
    return PriceFailureReportOut(
        total=len(rows),
        routed=sum(1 for r in rows if r[5]),
        groups=[
            PriceFailureGroupOut(supplier_slug=k[0], error=k[1], count=n)
            for k, n in sorted(groups.items(), key=lambda kv: -kv[1])
        ],
        items=items,
    )


def _error_kind(error: str | None) -> str:
    """The error without the per-row detail (an offer's name), so rows group."""
    text_ = (error or "").strip()
    if "«" in text_ and "»" in text_:
        head, _, rest = text_.partition("«")
        _, _, tail = rest.partition("»")
        text_ = f"{head}«…»{tail}"
    return text_[:120] or "—"


__all__ = ["PriceFailureReportOut", "price_failures"]
