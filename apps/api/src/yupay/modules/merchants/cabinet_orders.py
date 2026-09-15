"""One page of a merchant's own orders, for the cabinet's Orders section.

The machine API has no list endpoint and does not need one: a reseller's
system knows which orders it placed, and asks about them by the id it minted
(spec §9.1). A **person** looking at a screen has the opposite problem — they
want to see what happened today without knowing what to ask about — which is
why this lives on the BFF and not on ``/merchant/v1``.

Keyset pagination on ``(created_at, id)``, the same shape
``transactions.build`` uses and for the same reason: an offset page shifts
under a merchant whose orders keep arriving, so a reseller paging through a
busy morning would see rows twice and miss others.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from sqlalchemy import Select, String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ValidationError
from yupay.modules.catalog.models import Sku
from yupay.modules.merchants import deposit, transactions
from yupay.modules.merchants.cabinet_schemas import CabinetOrderRowOut, CabinetOrdersOut
from yupay.modules.orders.models import Order, OrderItem

#: An order with no charge posting has taken nothing, which is a real
#: answer for a row that failed before the debit.
_ZERO: Final = Decimal("0")

#: Statuses the cabinet offers as a filter. Anything else is refused rather
#: than silently ignored: a filter that quietly matches everything is worse
#: than one that says it does not exist.
FILTERS: Final[frozenset[str]] = frozenset(
    {"pending_payment", "paid", "fulfilling", "delivered", "failed", "cancelled", "refunded"}
)


def _scoped(merchant_id: str) -> Select[tuple[Order]]:
    """Every query here starts from the merchant, never from a request field."""
    return select(Order).where(Order.merchant_id == merchant_id)


async def build(
    db: AsyncSession,
    *,
    merchant_id: str,
    limit: int,
    cursor: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> CabinetOrdersOut:
    """One page of orders, newest first.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The authenticated merchant — the only scope.
        limit: Page size, already bounded by the route.
        cursor: A ``next_cursor`` from a previous page.
        status: One of :data:`FILTERS`, or ``None`` for all.
        search: Matched against the reseller's own ``merchant_order_id`` and
            against our order id. Both, because an operator pasting an id from
            a support chat does not always know whose id it is.

    Returns:
        The page, with ``next_cursor`` set only when older rows remain.

    Raises:
        ValidationError: An unknown status filter, or a malformed cursor.
    """
    query = _scoped(merchant_id)
    if status is not None:
        if status not in FILTERS:
            raise ValidationError("unknown status filter", code="unknown_status", status=status)
        query = query.where(Order.status == status)
    if search:
        needle = f"%{search.strip()}%"
        # ``Order.id`` is a Postgres ``uuid`` and there is no ``uuid ILIKE``
        # operator, so the cast is not a nicety: without it the whole search
        # answers 500 rather than answering nothing. Substring on both ids is
        # the documented behaviour — an operator pastes a fragment out of a
        # support chat as often as a whole id — and the merchant scope above
        # keeps the scan inside one account's orders, which is what the
        # ``idempotency_key`` half already costs.
        query = query.where(
            Order.idempotency_key.ilike(needle) | cast(Order.id, String).ilike(needle)
        )
    if cursor is not None:
        created_at, order_id = transactions.decode_cursor(cursor)
        # Strictly older, or the same instant and a smaller id — the tie-break
        # that stops a row appearing on two pages when two orders share a
        # timestamp, which they do under any real burst.
        query = query.where(
            (Order.created_at < created_at)
            | ((Order.created_at == created_at) & (Order.id < order_id))
        )

    rows = (
        (
            await db.execute(
                query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    page = list(rows[:limit])
    # ``(merchant_id, order_id)`` pairs: the scoping travels with every row so
    # a batch read cannot widen past the merchant the page belongs to.
    pairs = [(merchant_id, order.id) for order in page]
    charged = await deposit.charged_for_orders(db, pairs=pairs)
    refunded = await deposit.refunded_for_orders(db, pairs=pairs)

    codes = await _sku_codes(db, [order.id for order in page])

    items = [
        CabinetOrderRowOut(
            merchant_order_id=order.idempotency_key or "",
            order_id=order.id,
            status=order.status,
            sku_code=codes.get(order.id, ""),
            # The ledger, not the line: two of the three SKU shapes put a rate
            # or a face value on the line and the money somewhere else. Same
            # authority ``_out`` and ``order_status`` read.
            price_usd=charged.get(order.id, _ZERO),
            refunded_usd=refunded.get(order.id, _ZERO),
            created_at=order.created_at,
            delivered_at=order.delivered_at,
        )
        for order in page
    ]
    next_cursor = (
        transactions.encode_cursor(page[-1].created_at, page[-1].id)
        if len(rows) > limit and page
        else None
    )
    return CabinetOrdersOut(items=items, next_cursor=next_cursor)


async def _sku_codes(db: AsyncSession, order_ids: list[str]) -> dict[str, str]:
    """A human handle per order, in one query.

    Explicit rather than walking ``OrderItem.sku``, which is ``lazy="raise"``
    on purpose — the repo's answer to N+1 is to make the accidental version
    impossible rather than to notice it in a query-count test later. A merchant
    order has exactly one line (``merchants.orders`` builds it that way), so a
    plain join is the whole answer and no grouping is needed.
    """
    if not order_ids:
        return {}
    rows = (
        await db.execute(
            select(OrderItem.order_id, Sku.sku_code)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .where(OrderItem.order_id.in_(order_ids))
        )
    ).all()
    return {order_id: code for order_id, code in rows}


__all__ = ["FILTERS", "build"]
