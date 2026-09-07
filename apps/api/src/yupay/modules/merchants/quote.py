"""What a merchant may buy, and at what price — the quote step of an order.

Split out of ``orders.py`` (Task 5), which had grown to 468 lines carrying two
jobs at once. This is the first: **turn a ``sku_id`` and an ``expected_price``
into either a number we will charge or one of the documented RFC 7807
refusals**. ``orders.py`` keeps the second — idempotency, the deposit debit,
the order row, fulfilment.

The seam is worth having beyond the line count. Everything here is a *decision
about one line*, reads no ledger and writes no row, so the whole "can this be
ordered, and for how much" contract can be read in one file; and every refusal
code a merchant can meet before their deposit is touched is declared in one
place instead of being scattered through a placement flow.

Nothing about the price is *decided* here either — the formula is
``pricing.merchant_price`` over ``pricing.effective_cost``, the floor is
``pricing.violates_margin_floor``, the ±2 % accept/reject band is
``pricing.price_to_charge``, and buyability is ``orders.sku_is_buyable``,
shared with retail checkout. This module sequences them and names the failure.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.merchants import pricing

# Imported as a submodule rather than through the ``orders`` facade: that
# facade re-exports a router, so a facade import from here would pull the
# ``/api/v1`` route stack into a module ``bootstrap`` imports while it is still
# building that very stack. The same reason ``orders.service`` reaches for
# ``affiliate.discount`` directly, and ``payments.service`` for
# ``fulfillment.service``.
from yupay.modules.orders import service as orders

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.merchants.machine_schemas import MerchantOrderCreateIn
    from yupay.modules.merchants.models import Merchant

log = get_logger("yupay.merchants.quote")

#: RFC 7807 ``code`` values this path can return (spec §9.4). Constants rather
#: than literals at the raise sites: they are a published contract, and a typo
#: in one is a silent break for every integrator switching on it.
CODE_ITEM_UNAVAILABLE: Final = "item_unavailable"
CODE_PRICE_CHANGED: Final = "price_changed"
CODE_MARGIN_FLOOR: Final = "margin_floor"


def _unavailable(sku_id: str, reason: str) -> NotFoundError:
    """A 404 a reseller can act on without opening a support ticket.

    Ruling 2: ``/catalog`` listing a SKU is not a promise that sourcing can
    fill it, and this is the only place a merchant finds out. So the body says
    *which* condition failed — a SKU pulled from B2B distribution, one whose
    cost is missing, and one the supplier is out of are three different
    problems with three different answers, and a bare "not found" makes them
    all look like a bad id.

    Args:
        sku_id: The SKU asked for. Our own identifier, never PII.
        reason: The discriminator — see the module README's table.

    Returns:
        The error to raise.
    """
    return NotFoundError(
        "this SKU cannot be ordered right now",
        code=CODE_ITEM_UNAVAILABLE,
        sku_id=sku_id,
        reason=reason,
    )


async def load_orderable_sku(db: AsyncSession, *, sku_id: str) -> tuple[Sku, Decimal]:
    """Load a SKU and refuse it unless a merchant can buy it right now.

    Args:
        db: Session. The caller owns the transaction.
        sku_id: The SKU's id, already known to be a well-formed UUID (the
            schema parses it, so this never reaches Postgres as ``uuid = ''``
            — the ``DataError``-instead-of-a-clean-refusal trap
            ``merchant_id`` walked into in Task 2).

    Returns:
        The SKU with its product and brand loaded, and its wholesale cost.

    Raises:
        NotFoundError: ``item_unavailable``, with a ``reason``.
    """
    sku = (
        await db.execute(
            select(Sku)
            .options(selectinload(Sku.product).selectinload(Product.brand))
            .where(Sku.id == sku_id)
        )
    ).scalar_one_or_none()
    if sku is None:
        raise _unavailable(sku_id, "unknown_sku")
    product = sku.product
    brand = product.brand if product is not None else None
    if not sku.visible_b2b or brand is None or not brand.visible_b2b:
        raise _unavailable(sku_id, "not_b2b_visible")
    # The retail buyability rule, shared rather than restated: the active
    # chain, brand maintenance and supplier stock mean the same thing on both
    # surfaces, and a second copy of them would drift.
    if not orders.sku_is_buyable(sku):
        raise _unavailable(sku_id, "out_of_stock" if not sku.in_stock else "not_for_sale")
    if sku.variable_amount:
        # A customer-chosen amount has no wholesale price to quote: the B2B
        # formula is cost × markup, while these SKUs price off a guarded FX
        # rate and a margin multiplier. Not orderable in v1, and
        # ``expected_price`` would be meaningless for them.
        raise _unavailable(sku_id, "variable_amount")
    cost = pricing.effective_cost(sku)
    if cost is None:
        # Not sellable, never free — spec §8.2. The catalog withholds these
        # too, so reaching here means the SKU lost its cost between the poll
        # and the order.
        raise _unavailable(sku_id, "no_cost")
    return sku, cost


def price_for(sku: Sku, cost: Decimal, merchant: Merchant, body: MerchantOrderCreateIn) -> Decimal:
    """Our price for this merchant, reconciled against the one they quoted.

    Args:
        sku: The SKU being bought.
        cost: Its wholesale cost — :func:`pricing.effective_cost`'s result,
            already known not to be ``None``.
        merchant: The buyer, whose ``markup_adjustment_pp`` (dormant in v1)
            makes this price theirs rather than anyone's.
        body: The request, for ``expected_price``.

    Returns:
        The price to charge, which is always **ours**. ``expected_price`` is
        an accept/reject tolerance and not a bid (spec §8.4 as amended by the
        owner on 2026-09-07): inside the ±2% band the order proceeds at our
        number, never at the merchant's, and the reasoning is written out at
        :func:`pricing.price_to_charge`.

    Raises:
        ValidationError: ``margin_floor`` when our own price fails the floor,
            or ``price_changed`` when the merchant's number has drifted too
            far from it.
    """
    current = pricing.merchant_price(cost, pricing.merchant_markup_pct(sku, merchant))
    floor_pct = get_settings().merchant_margin_floor_pct
    if pricing.violates_margin_floor(cost, current, floor_pct):
        # The same guard ``price_list.build`` applies, reading the same
        # setting, so a SKU the catalog withheld is a SKU this refuses.
        log.warning(
            "merchant_order_below_margin_floor",
            sku_code=sku.sku_code,
            floor_pct=str(floor_pct),
            hint="b2b_markup_pct is below settings.merchant_margin_floor_pct; "
            "fix the markup in the admin catalog",
        )
        raise ValidationError(
            "this SKU's price does not clear our minimum margin",
            code=CODE_MARGIN_FLOOR,
            sku_id=sku.id,
        )
    charge = pricing.price_to_charge(current, body.expected_price)
    if charge is None:
        raise ValidationError(
            "the price has moved since you read it",
            code=CODE_PRICE_CHANGED,
            sku_id=sku.id,
            current_price=str(current),
            expected_price=str(body.expected_price),
        )
    return charge


__all__ = [
    "CODE_ITEM_UNAVAILABLE",
    "CODE_MARGIN_FLOOR",
    "CODE_PRICE_CHANGED",
    "load_orderable_sku",
    "price_for",
]
