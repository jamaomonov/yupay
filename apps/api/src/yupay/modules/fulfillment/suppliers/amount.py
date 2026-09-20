"""How many units one order line buys, for a supplier priced by amount.

Lifted out of the G-Engine adapter unchanged when NOVA's Fragment (Telegram)
endpoints needed the same answer. Two adapters computing "how many Stars" from
the same row is exactly the kind of duplication that drifts silently and then
buys somebody 1 Star instead of 5000, so there is one function and both call
it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from yupay.modules.fulfillment.suppliers.base import FulfillerError, MoneyOutcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.orders.models import OrderItem

#: A refusal raised before any call — our money never left.
_NOTHING_LEFT_OUR_BALANCE = MoneyOutcome.RETURNED


async def quantity_for(db: AsyncSession, *, item: OrderItem, mapping: Any) -> int | Decimal:
    """How many units to buy for one order line of an amount-priced service.

    Two sources of truth coexist here (dual-read), and the variable-amount
    one is checked *first*:

    - A ``variable_amount`` + ``units_per_usd`` line (Steam, and the
      pre-seed Stars free-amount SKU) re-derives its count from the money
      actually charged — checkout snapped it to a whole unit, so this
      reverses exactly that and cannot drift from what was paid. This
      reverse-engineer path is for any such SKU, not Stars-specific; do
      not delete it after the Stars seed.
    - Everything else is ``item.qty * mapping.quantity``. ``item.qty`` is
      *not* pinned to 1 for a package SKU — checkout allows up to
      ``DEFAULT_QTY_MAX`` packs of an ordinary SKU in one line — so this is
      genuinely "packs bought × units per pack" for those. After the Stars
      seed, the Stars mapping is ``quantity=1`` so the product collapses
      to ``item.qty`` (the customer's star count). Other products keep
      their pack ``mapping.quantity``.
    """
    from sqlalchemy import select

    from yupay.modules.catalog.models import Sku

    sku = (await db.execute(select(Sku).where(Sku.id == item.sku_id))).scalar_one_or_none()
    if sku is not None and sku.variable_amount and sku.units_per_usd:
        units = (item.unit_price_usd * sku.units_per_usd).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        if units > 0:
            return int(units)
        raise FulfillerError(
            f"variable amount {item.unit_price_usd} resolves to no units — refusing to order",
            money_outcome=_NOTHING_LEFT_OUR_BALANCE,
        )
    if sku is not None and sku.variable_amount:
        # A variable-amount SKU with no ``units_per_usd`` is denominated in
        # money itself — the Steam wallet in USD (G-Engine service 2). The
        # quantity *is* the face value the customer chose, cents kept: the
        # service declares ``Quantity`` as a Float and the customer may have
        # paid $10.50. Falling through to ``item.qty * mapping.quantity`` here
        # would send ``1`` for a $37 top-up, which is why this branch exists.
        # Not ``charged_usd``: the markup is ours, the supplier is paid the
        # amount the wallet receives.
        amount = item.unit_price_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount > 0:
            return amount
        raise FulfillerError(
            f"variable amount {item.unit_price_usd} resolves to nothing — refusing to order",
            money_outcome=_NOTHING_LEFT_OUR_BALANCE,
        )
    qty = int(item.qty) * int(mapping.quantity)
    # Both factors carry a DB `CHECK (... > 0)` (ck_order_items_qty_positive,
    # ck_sku_supplier_mapping_quantity_positive), so this is belt-and-suspenders
    # for a caller that hands in a non-persisted or duck-typed `item`/`mapping`
    # rather than a reachable state for a real order.
    if qty <= 0:
        raise FulfillerError(
            "quantity resolves to zero — refusing to order", money_outcome=_NOTHING_LEFT_OUR_BALANCE
        )
    return qty


__all__ = ["quantity_for"]
