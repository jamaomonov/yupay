"""What an order is actually worth to us, in USD.

``Order.total_usd`` is **not** that number, and reading it as if it were is the
bug this module exists to prevent. For a fixed-price SKU the two coincide:
``unit_price_usd`` is the retail price, and the margin sits between it and
``cost_usdt``. For a variable-amount SKU (Steam top-ups) they do not:
``unit_price_usd`` is the *face value the customer chose* — $10 of Steam
credit — while the price they were actually charged comes from
``display_rate = market_rate * sku.rate_multiplier`` (see
``modules/pricing/README.md``). A $10 Steam top-up at a 1.13 multiplier is
charged ~134 380 so'm, which is ~$11.30 at the market rate, not $10.

So summing ``total_usd`` to answer "how much has this customer spent" or "what
was revenue this week" silently understates every variable-amount order by the
whole markup — which is exactly the margin the business runs on.

The corrected figure is ``qty * unit_price_usd * rate_multiplier`` for variable
lines and ``qty * unit_price_usd`` for the rest. That is the same shape
``stats.analytics.business._margin_expr`` already uses for margin, and the two
stay consistent by construction: ``gross - margin == cost``.

**It is an approximation in one respect**: ``rate_multiplier`` is mutable from
the admin UI, so an order placed under an older multiplier is valued at
today's. The exact alternative — dividing ``total_charged`` by the order's
pinned ``fx_snapshot`` rate — is not usable: ``fx_snapshot_id`` is null on most
orders in practice (``_snapshot_id_for_rate`` returns ``None`` whenever it
cannot match the rate back to a row, and override-priced lines never set one).
Pinning the rate per order is the real fix and is worth doing before this
number is ever used for accounting rather than for operator context.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Case, Subquery, case, func, select

from yupay.modules.catalog.models import Sku
from yupay.modules.orders.models import OrderItem

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from yupay.modules.orders.models import Order

_CENTS = Decimal("0.01")


def charged_usd_expr() -> Case[Any]:
    """Per-order-item gross value in USD, for use inside ``func.sum(...)``.

    Variable-amount lines carry their markup in ``rate_multiplier`` (never
    null for them — ``ck_skus_variable_amount_complete`` enforces it), so the
    multiplier has to be applied to reach what was actually charged. Fixed
    lines are already priced at retail.

    Returns:
        A SQLAlchemy ``CASE``. Typed ``Case[Any]`` because SQLAlchemy's
        ``case()`` stub always returns ``Case[Any]`` regardless of branch type.
    """
    return case(
        (
            Sku.variable_amount.is_(True),
            OrderItem.qty * OrderItem.unit_price_usd * Sku.rate_multiplier,
        ),
        else_=OrderItem.qty * OrderItem.unit_price_usd,
    )


def order_charged_usd_subq() -> Subquery:
    """Per-order gross USD, as a joinable ``(order_id, charged_usd)`` subquery.

    Callers that already aggregate over ``Order`` rows (day buckets, per-user
    totals) can join this instead of restructuring their query: summing the
    item-level expression inline would fan the order rows out and inflate every
    ``COUNT`` beside it. Join it ``isouter=True`` and coalesce — an order with
    no items should still be counted, just valued at zero.
    """
    return (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(charged_usd_expr()).label("charged_usd"),
        )
        .join(Sku, Sku.id == OrderItem.sku_id)
        .group_by(OrderItem.order_id)
        .subquery()
    )


def order_charged_usd(order: Order) -> Decimal | None:
    """The same figure for one already-loaded order, rounded to cents.

    Requires ``order.items[].sku`` to be loaded — every admin read path does so
    through ``_order_load_options``, so this costs no extra query. Returns
    ``None`` when a line's SKU is missing rather than guessing a value, which
    keeps a broken row visibly empty instead of quietly under-reported.
    """
    total = Decimal("0")
    for item in order.items:
        sku = item.sku
        if sku is None:
            # Typed non-optional by the relationship, but the same defensive
            # branch `build_item_display` keeps: a row whose SKU was deleted
            # should not take a whole admin page down.
            return None  # type: ignore[unreachable]
        line = Decimal(item.qty) * item.unit_price_usd
        if sku.variable_amount and sku.rate_multiplier is not None:
            line *= sku.rate_multiplier
        total += line
    return total.quantize(_CENTS, rounding=ROUND_HALF_UP)


__all__ = ["charged_usd_expr", "order_charged_usd", "order_charged_usd_subq"]
