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

The multiplier comes from the order line itself, frozen at checkout
(``OrderItem.rate_multiplier``, ADR-0051) — an order's worth must not be a
function of today's pricing config, and it used to be: editing a SKU's margin
revalued every order ever placed against it. Lines written before that column
existed have ``NULL`` there and fall back to the live SKU; that is a knowingly
approximate valuation, kept rather than backfilled so a guess never becomes
indistinguishable from a recorded fact. See the ADR for why the pre-existing
``Order.fx_snapshot_id`` could not serve this purpose.
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

    Prefers the multiplier frozen on the line at checkout (ADR-0051), so an
    admin editing a SKU's margin cannot revalue orders already taken. Falls
    back to the live SKU only for lines written before that column existed,
    where ``NULL`` means "not recorded" rather than "no markup" — those keep
    reporting exactly as they did before, which is the best that can honestly
    be said about them. Fixed lines are already priced at retail either way.

    Returns:
        A SQLAlchemy ``CASE``. Typed ``Case[Any]`` because SQLAlchemy's
        ``case()`` stub always returns ``Case[Any]`` regardless of branch type.
    """
    return case(
        (
            OrderItem.rate_multiplier.isnot(None),
            OrderItem.qty * OrderItem.unit_price_usd * OrderItem.rate_multiplier,
        ),
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
        # Same precedence as `charged_usd_expr`: the rate frozen on the line
        # wins, the live SKU is only the pre-ADR-0051 fallback.
        if item.rate_multiplier is not None:
            line *= item.rate_multiplier
        elif sku.variable_amount and sku.rate_multiplier is not None:
            line *= sku.rate_multiplier
        total += line
    return total.quantize(_CENTS, rounding=ROUND_HALF_UP)


__all__ = ["charged_usd_expr", "order_charged_usd", "order_charged_usd_subq"]
