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
from typing import TYPE_CHECKING, Final

from sqlalchemy import Select, String, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from yupay.core.errors import ValidationError
from yupay.modules.catalog.models import Brand, BrandTranslation, Product, Sku
from yupay.modules.merchants import deposit, order_status, transactions
from yupay.modules.merchants.cabinet_schemas import (
    CabinetOrderDetailOut,
    CabinetOrderRowOut,
    CabinetOrdersOut,
)
from yupay.modules.orders.models import Order, OrderItem

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from yupay.modules.merchants.models import Merchant

#: An order with no charge posting has taken nothing, which is a real
#: answer for a row that failed before the debit.
_ZERO: Final = Decimal("0")

#: What ``_sku_labels`` falls back to when a brand has no translation in the
#: requested locale. The cabinet has no ``Accept-Language`` plumbing today —
#: unlike ``catalog.service``, which resolves the caller's locale from the
#: request — so both call sites below pass this same value as ``locale``,
#: making the fallback join a no-op until that plumbing exists. It stays a
#: real parameter rather than being folded away so that day is a one-line
#: change here, not a new query.
DEFAULT_LOCALE: Final = "ru"

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
        # Escape what ILIKE treats as a pattern before wrapping it in one.
        # Without this, typing ``_`` matches every order and ``%`` matches
        # every order, which reads as a broken search rather than as a
        # feature nobody documented. There is no injection either way — the
        # needle is a bind parameter — this is about the answer being right.
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        needle = f"%{escaped}%"
        # ``Order.id`` is a Postgres ``uuid`` and there is no ``uuid ILIKE``
        # operator, so the cast is not a nicety: without it the whole search
        # answers 500 rather than answering nothing. Substring on both ids is
        # the documented behaviour — an operator pastes a fragment out of a
        # support chat as often as a whole id — and the merchant scope above
        # keeps the scan inside one account's orders, which is what the
        # ``idempotency_key`` half already costs.
        query = query.where(
            Order.idempotency_key.ilike(needle, escape="\\")
            | cast(Order.id, String).ilike(needle, escape="\\")
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

    labels = await _sku_labels(db, [order.id for order in page], DEFAULT_LOCALE)

    items = []
    for order in page:
        sku_code, sku_name, brand_name = labels.get(order.id, ("", None, None))
        items.append(
            CabinetOrderRowOut(
                merchant_order_id=order.idempotency_key or "",
                order_id=order.id,
                status=order.status,
                sku_code=sku_code,
                sku_name=sku_name,
                brand_name=brand_name,
                # The ledger, not the line: two of the three SKU shapes put a
                # rate or a face value on the line and the money somewhere
                # else. Same authority ``_out`` and ``order_status`` read.
                price_usd=charged.get(order.id, _ZERO),
                refunded_usd=refunded.get(order.id, _ZERO),
                created_at=order.created_at,
                delivered_at=order.delivered_at,
            )
        )
    next_cursor = (
        transactions.encode_cursor(page[-1].created_at, page[-1].id)
        if len(rows) > limit and page
        else None
    )
    return CabinetOrdersOut(items=items, next_cursor=next_cursor)


async def read_detail(
    db: AsyncSession, *, merchant: Merchant, merchant_order_id: str
) -> CabinetOrderDetailOut:
    """One order in full, named.

    ``order_status.read`` is the reader — the same one the machine API polls,
    so the cabinet and a reseller's own polling never describe one order two
    ways (its own docstring). This wraps that call and adds the one thing a
    person's screen wants and a signed API caller does not: the product's
    name, from :func:`_sku_labels`.

    Args:
        db: Session. The caller owns the transaction.
        merchant: The authenticated, non-frozen merchant — ``order_status.read``'s
            only source of scope.
        merchant_order_id: The reseller's id for the order (``manual-<uuid>``
            for a cabinet-placed one), already percent-decoded by the router.

    Returns:
        The order, with ``sku_code``, ``sku_name`` and ``brand_name`` filled
        in alongside everything ``order_status.read`` already carries.

    Raises:
        NotFoundError: ``order_not_found`` — propagated from ``order_status.read``.
    """
    status = await order_status.read(db, merchant=merchant, merchant_order_id=merchant_order_id)
    labels = await _sku_labels(db, [status.order_id], DEFAULT_LOCALE)
    sku_code, sku_name, brand_name = labels.get(status.order_id, ("", None, None))
    return CabinetOrderDetailOut(
        merchant_order_id=status.merchant_order_id,
        order_id=status.order_id,
        status=status.status,
        sku_id=status.sku_id,
        sku_code=sku_code,
        sku_name=sku_name,
        brand_name=brand_name,
        price_usd=status.price_usd,
        refunded_usd=status.refunded_usd,
        created_at=status.created_at,
        paid_at=status.paid_at,
        delivered_at=status.delivered_at,
        failure_reason=status.failure_reason,
        delivery=status.delivery,
        timeline=status.timeline,
    )


async def _sku_labels(
    db: AsyncSession, order_ids: list[str], locale: str
) -> dict[str, tuple[str, str | None, str | None]]:
    """A human handle per order, in one query: ``(sku_code, sku_name, brand_name)``.

    Explicit rather than walking ``OrderItem.sku``, which is ``lazy="raise"``
    on purpose — the repo's answer to N+1 is to make the accidental version
    impossible rather than to notice it in a query-count test later. A merchant
    order has exactly one line (``merchants.orders`` builds it that way), so a
    plain join is the whole answer and no grouping is needed.

    ``sku_name`` is ``Sku.denomination`` — nullable on the model, so a SKU
    with none on file answers ``None`` there rather than an empty string.
    ``brand_name`` is the brand's :class:`BrandTranslation` in ``locale``,
    falling back to :data:`DEFAULT_LOCALE` when that row is missing — two
    outer joins on the same table, keyed ``(brand_id, locale)``, rather than a
    second round trip or a Python-side pick over a preloaded list (the way
    ``catalog.service`` does it): this module has no request-scoped list of
    translations to pick from, and a second query per page would be the N+1
    the docstring above is written to avoid.

    ``OrderItem.sku_id`` is ``ON DELETE RESTRICT`` and every join above it is
    an inner join, so an order actually missing from the returned mapping
    would mean its ``OrderItem`` row itself is missing — which does not
    happen for a stored merchant order. Callers still default it (``("",
    None, None)``): a defensive fallback costs one line and cannot go stale.

    Args:
        db: Session. The caller owns the transaction.
        order_ids: Orders to label. Scoping is the caller's — both current
            callers already start from a query filtered to one merchant.
        locale: Preferred locale for ``brand_name``.

    Returns:
        ``order_id -> (sku_code, sku_name, brand_name)``.
    """
    if not order_ids:
        return {}
    wanted = aliased(BrandTranslation)
    fallback = aliased(BrandTranslation)
    rows = (
        await db.execute(
            select(
                OrderItem.order_id,
                Sku.sku_code,
                Sku.denomination,
                func.coalesce(wanted.name, fallback.name),
            )
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .outerjoin(wanted, and_(wanted.brand_id == Brand.id, wanted.locale == locale))
            .outerjoin(
                fallback,
                and_(fallback.brand_id == Brand.id, fallback.locale == DEFAULT_LOCALE),
            )
            .where(OrderItem.order_id.in_(order_ids))
        )
    ).all()
    return {
        order_id: (sku_code, denomination, brand_name)
        for order_id, sku_code, denomination, brand_name in rows
    }


__all__ = ["DEFAULT_LOCALE", "FILTERS", "build", "read_detail"]
