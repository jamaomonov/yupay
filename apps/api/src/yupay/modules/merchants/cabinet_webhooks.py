"""The cabinet's delivery log — one page of a merchant's own webhook attempts.

The one read on this surface with no twin anywhere else. `admin_routes` can
configure a hook and report its health (`failure_streak`, the two timestamps),
but nothing until now could answer the question a reseller actually asks:
*"we say the 14:02 event never arrived — what did you send, where, and what
came back?"*

`MerchantWebhookDelivery` was built to answer it — the docstring on that model
calls itself "M4's delivery log" and carries an index on
`(merchant_id, created_at DESC)` for exactly this query. This module is the
reader that index was waiting for.

Keyset paging on `(created_at, id)`, the same shape `transactions.build` and
`cabinet_orders.build` use: the log is written by the worker while it is read
by a person, so an offset page would repeat an attempt and skip another.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.merchants import transactions
from yupay.modules.merchants.cabinet_schemas import (
    CabinetDeliveriesOut,
    CabinetDeliveryRowOut,
)
from yupay.modules.merchants.models import MerchantWebhookDelivery

#: A page big enough to cover an incident's worth of retries without paging.
DEFAULT_LIMIT: Final = 25


async def list_deliveries(
    db: AsyncSession,
    *,
    merchant_id: str,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> CabinetDeliveriesOut:
    """One page of this merchant's delivery attempts, newest first.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Taken from the signed-in operator, never from a request
            field — the rule every route on this surface rests on.
        limit: Rows per page, already clamped by the route.
        cursor: An opaque `(created_at, id)` keyset cursor from a previous
            page, or ``None`` for the newest one.

    Returns:
        The page, with ``next_cursor`` set only while older rows remain.

    Raises:
        ValidationError: A malformed cursor.
    """
    query = select(MerchantWebhookDelivery).where(
        MerchantWebhookDelivery.merchant_id == merchant_id
    )
    if cursor is not None:
        created_at, delivery_id = transactions.decode_cursor(cursor)
        query = query.where(
            (MerchantWebhookDelivery.created_at < created_at)
            | (
                (MerchantWebhookDelivery.created_at == created_at)
                & (MerchantWebhookDelivery.id < delivery_id)
            )
        )

    rows = (
        (
            await db.execute(
                query.order_by(
                    MerchantWebhookDelivery.created_at.desc(),
                    MerchantWebhookDelivery.id.desc(),
                ).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    page = list(rows[:limit])
    items = [CabinetDeliveryRowOut.model_validate(row) for row in page]
    next_cursor = (
        transactions.encode_cursor(page[-1].created_at, page[-1].id)
        if len(rows) > limit and page
        else None
    )
    return CabinetDeliveriesOut(items=items, next_cursor=next_cursor)


__all__ = ["DEFAULT_LIMIT", "list_deliveries"]
