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
from typing import TYPE_CHECKING, Final, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.catalog.unit_sku import assert_qty_allowed, is_unit_sku
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


def unavailable(sku_id: str, reason: str) -> NotFoundError:
    """A 404 a reseller can act on without opening a support ticket.

    Ruling 2: ``/catalog`` listing a SKU is not a promise that sourcing can
    fill it, and this is the only place a merchant finds out. So the body says
    *which* condition failed — a SKU pulled from B2B distribution, one whose
    cost is missing, and one the supplier is out of are three different
    problems with three different answers, and a bare "not found" makes them
    all look like a bad id.

    Public, and paired with :func:`unavailable_brand`: this API refuses a SKU
    it cannot order and a brand it cannot check with the same `code` and
    `reason` vocabulary, so an integrator switching on either sees one
    contract — only the identifier's own key and wording differ, one per
    caller-supplied id shape.

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


def unavailable_brand(brand_slug: str, reason: str) -> NotFoundError:
    """:func:`unavailable`'s sibling for a brand-scoped refusal.

    Two functions rather than one generic one, because the identifier the
    caller sent must come back under the name they sent it: a merchant who
    posted ``{"brand": "no-such-brand"}`` and gets a 404 back with a bare
    ``sku_id`` field has to guess whether that is their brand slug echoed
    under the wrong key or a stray SKU id from somewhere else. Same
    ``item_unavailable`` code and the same ``reason`` vocabulary as
    :func:`unavailable` — ``validate.py``'s brand-scoped check is the only
    caller today (``unknown_brand`` / ``not_b2b_visible``) — so an integrator
    switching on ``code`` and ``reason`` sees one contract either way; only
    the identifier's key and the message name what kind of id failed.

    Args:
        brand_slug: The brand asked for. Our own identifier, never PII.
        reason: The discriminator — see the module README's table.

    Returns:
        The error to raise.
    """
    return NotFoundError(
        "this brand cannot be ordered from",
        code=CODE_ITEM_UNAVAILABLE,
        brand=brand_slug,
        reason=reason,
    )


#: ``quantity`` missing on a SKU sold by the unit. Not defaulted to 1: that
#: would sell one Telegram Star and charge two cents for it.
CODE_QUANTITY_REQUIRED: Final = "quantity_required"

#: ``quantity`` sent for a fixed denomination. Not ignored: a merchant who
#: sent it believes they bought that many, and silently charging for one is
#: the same bug in the direction that costs them goods instead of money.
CODE_QUANTITY_NOT_ACCEPTED: Final = "quantity_not_accepted"

#: ``quantity`` outside the SKU's published ``min_qty``/``max_qty``.
CODE_QUANTITY_OUT_OF_RANGE: Final = "quantity_out_of_range"

#: ``amount_usd`` missing on a balance loaded in dollars (the Steam wallet).
CODE_AMOUNT_REQUIRED: Final = "amount_required"

#: ``amount_usd`` sent for a SKU that is not sized in dollars.
CODE_AMOUNT_NOT_ACCEPTED: Final = "amount_not_accepted"

#: ``amount_usd`` outside the SKU's published bounds.
CODE_AMOUNT_OUT_OF_RANGE: Final = "amount_out_of_range"


class OrderShape(NamedTuple):
    """How one merchant order line is sized.

    The three shapes are mutually exclusive by construction — a SKU is a fixed
    denomination, or counted in units, or loaded in dollars — and this is the
    one place that decides which, so the catalog and the order path cannot
    disagree about what a SKU wants.
    """

    #: Goes on ``OrderItem.qty``. Always ``1`` except for a unit SKU, where it
    #: is the count fulfilment delivers.
    qty: int
    #: Face value for a variable-amount SKU, ``None`` otherwise. Goes on the
    #: line as ``unit_price_usd`` — what the supplier is told to load — and is
    #: *not* what the merchant pays.
    amount_usd: Decimal | None


def resolve_shape(sku: Sku, body: MerchantOrderCreateIn) -> OrderShape:
    """Read the request's sizing against the SKU's shape, refusing every
    mismatch in both directions.

    Nothing is defaulted. Each missing-or-extra field has a wrong answer that
    would go through silently: no quantity sells one Star, no amount sells
    nothing, an ignored quantity charges for one denomination out of ten, an
    ignored amount loads a wallet with the wrong sum.

    Args:
        sku: The SKU being bought.
        body: The request.

    Returns:
        What to put on the order line.

    Raises:
        ValidationError: One of the six ``quantity_*`` / ``amount_*`` codes.
    """
    if sku.variable_amount:
        if body.quantity is not None:
            raise ValidationError(
                "this SKU is loaded by amount, not by quantity",
                code=CODE_QUANTITY_NOT_ACCEPTED,
                sku_id=sku.id,
            )
        if body.amount_usd is None:
            raise ValidationError(
                "this SKU is loaded in dollars and needs an amount",
                code=CODE_AMOUNT_REQUIRED,
                sku_id=sku.id,
                min_amount_usd=str(sku.min_amount_usd),
                max_amount_usd=str(sku.max_amount_usd),
            )
        low, high = sku.min_amount_usd, sku.max_amount_usd
        if low is None or high is None or not (low <= body.amount_usd <= high):
            raise ValidationError(
                "amount is outside this SKU's range",
                code=CODE_AMOUNT_OUT_OF_RANGE,
                sku_id=sku.id,
                min_amount_usd=str(low),
                max_amount_usd=str(high),
            )
        return OrderShape(qty=1, amount_usd=body.amount_usd)
    if body.amount_usd is not None:
        raise ValidationError(
            "this SKU is not loaded in dollars and takes no amount",
            code=CODE_AMOUNT_NOT_ACCEPTED,
            sku_id=sku.id,
        )
    return OrderShape(qty=resolve_quantity(sku, body.quantity), amount_usd=None)


def resolve_quantity(sku: Sku, quantity: int | None) -> int:
    """How many units this order buys, refusing every other reading.

    The FIXED/UNFIXED split, which this codebase already draws with
    :func:`catalog.unit_sku.is_unit_sku`: a fixed denomination is bought one
    at a time, a unit SKU is a currency and needs an amount. Both mismatches
    are refused rather than defaulted, in both directions, because each
    default is a silent wrong answer — one sells a single Star, the other
    charges for one denomination while the merchant believes they bought ten.

    Args:
        sku: The SKU being bought.
        quantity: The request's ``quantity``, or ``None``.

    Returns:
        The quantity to put on the order line — always ``1`` for a fixed SKU.

    Raises:
        ValidationError: One of the three ``quantity_*`` codes.
    """
    if not is_unit_sku(sku):
        if quantity is not None:
            raise ValidationError(
                "this SKU is a fixed denomination and takes no quantity",
                code=CODE_QUANTITY_NOT_ACCEPTED,
                sku_id=sku.id,
            )
        return 1
    if quantity is None:
        raise ValidationError(
            "this SKU is sold by the unit and needs a quantity",
            code=CODE_QUANTITY_REQUIRED,
            sku_id=sku.id,
            min_qty=sku.min_qty,
            max_qty=sku.max_qty,
        )
    try:
        # The same bounds the storefront enforces, read off the same columns
        # the price list published — one gate, so a merchant cannot be told a
        # range the order path disagrees with.
        assert_qty_allowed(sku, quantity)
    except ValidationError as exc:
        raise ValidationError(
            "quantity is outside this SKU's range",
            code=CODE_QUANTITY_OUT_OF_RANGE,
            sku_id=sku.id,
            min_qty=sku.min_qty,
            max_qty=sku.max_qty,
        ) from exc
    return quantity


async def load_orderable_sku(db: AsyncSession, *, sku_id: str) -> tuple[Sku, Decimal | None]:
    """Load a SKU and refuse it unless a merchant can buy it right now.

    Args:
        db: Session. The caller owns the transaction.
        sku_id: The SKU's id, already known to be a well-formed UUID (the
            schema parses it, so this never reaches Postgres as ``uuid = ''``
            — the ``DataError``-instead-of-a-clean-refusal trap
            ``merchant_id`` walked into in Task 2).

    Returns:
        The SKU with its product and brand loaded, and its wholesale cost —
        ``None`` for a variable-amount SKU, whose cost is the face value on
        the request rather than a column.

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
        raise unavailable(sku_id, "unknown_sku")
    product = sku.product
    brand = product.brand if product is not None else None
    if not sku.visible_b2b or brand is None or not brand.visible_b2b:
        raise unavailable(sku_id, "not_b2b_visible")
    # The retail buyability rule, shared rather than restated: the active
    # chain, brand maintenance and supplier stock mean the same thing on both
    # surfaces, and a second copy of them would drift.
    if not orders.sku_is_buyable(sku):
        raise unavailable(sku_id, "out_of_stock" if not sku.in_stock else "not_for_sale")
    if sku.variable_amount:
        # Priced off the face value the merchant names, not off a column —
        # see ``pricing.merchant_amount_price``. ``cost`` is therefore not
        # knowable here (it is the amount, which lives on the request), and
        # ``None`` says so rather than standing for "free".
        #
        # Retail prices these off a guarded FX rate times a margin multiplier,
        # which is why they were refused outright until 2026-09-15: a spread
        # on a conversion is not available when the buyer already holds
        # dollars. The bounds still have to exist, or there is nothing to
        # validate the amount against.
        if sku.min_amount_usd is None or sku.max_amount_usd is None:  # pragma: no cover
            # Unreachable through the database: ``ck_skus_variable_amount_complete``
            # requires both bounds (and a rate multiplier) on any row that sets
            # ``variable_amount``. Kept because this function decides whether
            # money may move, and the check costs a comparison — if that
            # constraint is ever relaxed, this refuses rather than validating
            # an amount against ``None``.
            raise unavailable(sku_id, "variable_amount")
        return sku, None
    cost = pricing.effective_cost(sku)
    if cost is None:
        # Not sellable, never free — spec §8.2. The catalog withholds these
        # too, so reaching here means the SKU lost its cost between the poll
        # and the order.
        raise unavailable(sku_id, "no_cost")
    return sku, cost


class MerchantQuote(NamedTuple):
    """What one merchant order costs, as its two distinct numbers.

    They are not the same quantity and a single "price" cannot be both:
    ``unit_price`` is a rate at six decimals that goes on the order line and
    that the price list published, while ``total`` is money at the cent, which
    is what leaves the deposit. For a fixed denomination they coincide at
    ``qty=1``; for a thousand Telegram Stars they are $0.016537 and $16.54.
    """

    #: Six decimals — recorded as ``order_items.unit_price_usd``.
    unit_price: Decimal
    #: Whole cents — charged to the deposit, and the authority for a refund.
    total: Decimal


def price_for(
    sku: Sku,
    cost: Decimal | None,
    merchant: Merchant,
    body: MerchantOrderCreateIn,
    *,
    shape: OrderShape,
) -> MerchantQuote:
    """Our price for this merchant, reconciled against the one they quoted.

    Args:
        sku: The SKU being bought.
        cost: Its wholesale cost — :func:`pricing.effective_cost`'s result,
            already known not to be ``None``.
        merchant: The buyer, whose ``markup_adjustment_pp`` (dormant in v1)
            makes this price theirs rather than anyone's.
        body: The request, for ``expected_price``.
        shape: :func:`resolve_shape`'s result — how the line is sized.

    Returns:
        The rate and the money, both **ours**. ``expected_price`` is an
        accept/reject tolerance and not a bid (spec §8.4 as amended by the
        owner on 2026-09-07): inside the ±2% band the order proceeds at our
        number, never at the merchant's, and the reasoning is written out at
        :func:`pricing.price_to_charge`. It is compared against the **total**,
        which is what a merchant is asked to send and what they pay.

    Raises:
        ValidationError: ``margin_floor`` when our own price fails the floor,
            or ``price_changed`` when the merchant's number has drifted too
            far from it.
    """
    markup = pricing.merchant_markup_pct(sku, merchant)
    if shape.amount_usd is not None:
        # A dollar of balance costs us a dollar, so the face value IS the
        # cost — see ``pricing.merchant_amount_price``.
        basis = shape.amount_usd
        unit = pricing.merchant_unit_price(Decimal("1"), markup)
        current = pricing.merchant_amount_price(shape.amount_usd, markup)
    else:
        assert cost is not None, "a non-variable SKU always carries a cost here"
        basis = cost * shape.qty
        unit = pricing.merchant_unit_price(cost, markup)
        current = pricing.merchant_order_total(unit, shape.qty)
    floor_pct = get_settings().merchant_margin_floor_pct
    # Against the cost of what is actually being bought, so the floor means the
    # same thing at any quantity — and, at ``qty=1``, exactly what it meant
    # before quantity existed.
    if pricing.violates_margin_floor(basis, current, floor_pct):
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
    return MerchantQuote(unit_price=unit, total=charge)


__all__ = [
    "CODE_AMOUNT_NOT_ACCEPTED",
    "CODE_AMOUNT_OUT_OF_RANGE",
    "CODE_AMOUNT_REQUIRED",
    "CODE_ITEM_UNAVAILABLE",
    "CODE_MARGIN_FLOOR",
    "CODE_PRICE_CHANGED",
    "CODE_QUANTITY_NOT_ACCEPTED",
    "CODE_QUANTITY_OUT_OF_RANGE",
    "CODE_QUANTITY_REQUIRED",
    "MerchantQuote",
    "OrderShape",
    "load_orderable_sku",
    "price_for",
    "resolve_quantity",
    "resolve_shape",
    "unavailable",
    "unavailable_brand",
]
