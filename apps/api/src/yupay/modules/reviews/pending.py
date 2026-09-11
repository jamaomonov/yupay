"""Catch-up review ask: the unreviewed delivered order to prompt on next session.

The Mini App (and logged-in web) call this after bootstrap. It deliberately
ignores orders younger than :data:`PENDING_ASK_MIN_AGE` so the prompt never
overlays the same session as delivery — the buyer left to check the game and
comes back later. See ADR-0039.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.core.clock import now
from yupay.modules.catalog.models import Brand, BrandTranslation, Product, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.reviews.models import Review

#: Floor so "I switched to the game to check UC" is not the same session.
PENDING_ASK_MIN_AGE = timedelta(hours=2)
#: Ceiling so a three-week-old top-up does not surface as "how was that?".
PENDING_ASK_MAX_AGE = timedelta(days=14)


class PendingAsk(NamedTuple):
    """One order the catch-up prompt should ask about."""

    order_id: str
    brand_slug: str
    brand_name: str
    delivered_at: datetime


def _name_subquery(locale: str) -> ColumnElement[str]:
    """Scalar subquery: brand name in ``locale``, else Russian, else the slug."""
    loc = locale[:3]
    named = (
        select(BrandTranslation.name)
        .where(BrandTranslation.brand_id == Brand.id, BrandTranslation.locale == loc)
        .limit(1)
        .correlate(Brand)
        .scalar_subquery()
    )
    russian = (
        select(BrandTranslation.name)
        .where(BrandTranslation.brand_id == Brand.id, BrandTranslation.locale == "ru")
        .limit(1)
        .correlate(Brand)
        .scalar_subquery()
    )
    return func.coalesce(named, russian, Brand.slug)


async def pending_ask(db: AsyncSession, *, user_id: str, locale: str) -> PendingAsk | None:
    """Most recent delivered unreviewed catalog order old enough to ask about.

    Merchant and wallet-top-up orders are excluded: there is no retail brand
    to rate. One row — the newest match — so the prompt never stacks.
    """
    cutoff_fresh = now() - PENDING_ASK_MIN_AGE
    cutoff_old = now() - PENDING_ASK_MAX_AGE
    row = (
        await db.execute(
            select(
                Order.id,
                Brand.slug,
                _name_subquery(locale),
                Order.delivered_at,
            )
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                Order.user_id == user_id,
                Order.status == "delivered",
                Order.merchant_id.is_(None),
                Order.purpose == "catalog",
                Order.delivered_at.is_not(None),
                Order.delivered_at <= cutoff_fresh,
                Order.delivered_at >= cutoff_old,
                ~select(Review.id).where(Review.order_id == Order.id).exists(),
            )
            .order_by(Order.delivered_at.desc())
            .limit(1)
        )
    ).first()
    if row is None or row[3] is None:
        return None
    return PendingAsk(
        order_id=row[0],
        brand_slug=row[1],
        brand_name=row[2],
        delivered_at=row[3],
    )


__all__ = ["PENDING_ASK_MAX_AGE", "PENDING_ASK_MIN_AGE", "PendingAsk", "pending_ask"]
