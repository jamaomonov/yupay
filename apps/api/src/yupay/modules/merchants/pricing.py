"""The one home for the merchant B2B wholesale price formula.

::

    price = ceil_to_cent(
        effective_cost(sku)
        * (1 + (sku.b2b_markup_pct + (merchant.markup_adjustment_pp or 0)) / 100)
    )

Per ``docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md`` (Task 5):
**nothing else in the codebase may reimplement this formula.** Every
caller — the machine-API catalog, merchant order pricing, cabinet display,
CSV export, and the admin price preview (Task 8) — must call
:func:`effective_cost`, :func:`merchant_markup_pct`, :func:`merchant_price`,
and :func:`violates_margin_floor` directly, never re-derive the arithmetic
inline. This is the same lesson ``uzsWord`` (``packages/utils/src/money.ts``)
already taught the hard way: its UZS pluralisation logic drifted into three
diverging copies before being consolidated into one function. One formula,
one home, here.

See ``docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`` §8 for the
full pricing design.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yupay.modules.catalog.models import Sku
    from yupay.modules.merchants.models import Merchant

_CENT = Decimal("0.01")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def effective_cost(sku: Sku) -> Decimal | None:
    """The wholesale cost a merchant's price is built on.

    Reads ``sku.cost_usdt``. ``None`` means the SKU is not sellable B2B:
    excluded from the merchant catalog, and orders for it are rejected —
    never priced from a fallback figure, which would either give away
    margin or look like price-gouging depending on which way the fallback
    happened to be wrong (spec §8.2).

    Gift SKUs are out of v1. When they join, this is the only function that
    learns about their live regional cost — no other caller should grow its
    own gift-cost special case (spec §8.2).

    Args:
        sku: The catalog SKU being priced for a merchant.

    Returns:
        The cost in USDT, or ``None`` if the SKU has no recorded cost.
    """
    return sku.cost_usdt


def merchant_markup_pct(sku: Sku, merchant: Merchant) -> Decimal:
    """The markup percentage a merchant pays over cost for this SKU.

    ``sku.b2b_markup_pct`` is per-SKU and uniform across every merchant —
    prices are visible to every registered merchant, so they must be
    uniform (spec §8.3). ``merchant.markup_adjustment_pp`` is a dormant
    per-merchant override in percentage points (e.g. ``-2`` for a
    negotiated high-volume deal), applied uniformly across that merchant's
    whole catalog; it is ``None`` for every merchant in v1.

    Args:
        sku: The SKU whose base markup applies.
        merchant: The merchant buying it, whose adjustment (if any) is added.

    Returns:
        The effective markup percentage, e.g. ``Decimal("7")`` for 7%.
    """
    return sku.b2b_markup_pct + (merchant.markup_adjustment_pp or _ZERO)


def merchant_price(cost: Decimal, markup_pct: Decimal) -> Decimal:
    """The wholesale price a merchant pays: cost plus markup, rounded up.

    Rounding is always up, to the cent (``ROUND_CEILING``) — rounding down
    would erase margin on cheap SKUs one invisible cent at a time.

    ``markup_pct`` is not validated here. A negative value (a fat-fingered
    per-SKU ``b2b_markup_pct``, e.g. ``-7`` typed for ``7`` — nothing in the
    schema stops it, see Task 4) is applied exactly as the formula says,
    producing a price mathematically below ``cost``. Catching that is
    :func:`violates_margin_floor`'s job, not this function's: keeping the
    arithmetic pure and the guard separate is what lets the guard see every
    price this function computes, instead of this function quietly refusing
    some of them on its own judgment.

    Args:
        cost: The SKU's wholesale cost — :func:`effective_cost`'s result;
            callers must have already handled ``None``.
        markup_pct: The markup percentage from :func:`merchant_markup_pct`.

    Returns:
        The price, quantized to two decimal places, rounded up.
    """
    return (cost * (Decimal("1") + markup_pct / _HUNDRED)).quantize(_CENT, rounding=ROUND_CEILING)


def violates_margin_floor(cost: Decimal, price: Decimal, floor_pct: Decimal) -> bool:
    """Whether ``price`` fails to clear the minimum margin over ``cost``.

    This is the only global pricing control (spec §8.3): it catches a
    fat-fingered per-SKU markup (``0.5`` typed for ``5``, or a markup that
    went negative outright — Task 4 deliberately added no DB CHECK on
    ``b2b_markup_pct``, so this function is what stands between that typo
    and an order) and cost spikes a stale per-SKU markup no longer covers.

    Args:
        cost: The SKU's wholesale cost.
        price: The computed merchant price — :func:`merchant_price`'s
            result.
        floor_pct: The minimum acceptable margin over cost, e.g.
            ``settings.merchant_margin_floor_pct``.

    Returns:
        ``True`` if ``price`` is below ``cost * (1 + floor_pct / 100)``.
    """
    return price < cost * (Decimal("1") + floor_pct / _HUNDRED)


#: How far a merchant's quoted price may sit from ours and still execute
#: (spec §8.4). The band is symmetric and expressed as a percentage of OUR
#: price, which is the only figure both sides can recompute.
PRICE_DRIFT_TOLERANCE_PCT = Decimal("2")


def price_to_charge(current: Decimal, expected: Decimal) -> Decimal | None:
    """What an order executes at, given our price and the merchant's.

    Spec §8.4 as amended by the owner on 2026-09-07: ``expected_price`` is an
    accept/reject tolerance and never a bid. Drift within
    ±:data:`PRICE_DRIFT_TOLERANCE_PCT` executes at **our** current price;
    anything beyond it is a ``price_changed`` rejection carrying that price.
    This function is the rule's single home — the order path calls it and
    decides nothing about drift on its own, so changing the policy is a change
    here and nowhere else.

    **Why ours, and not the lower of the two.** The rule was first written as
    ``min(current, expected)``, carried over from the Steam-gifts flow where
    the counterparty is a human who cannot compute the exploit. Here the
    counterparty is a machine that can, and the leak ran one way only:

    - ``/catalog`` is live-computed and never cached, so a merchant could read
      our price moments before ordering and then send
      ``expected_price = current × 0.98``. Drift is exactly the tolerance, the
      band accepts it, and ``min()`` took their number — a guaranteed 2% off
      wholesale on every order, obtained by reading our own documentation. On
      the default 7% markup that is about **31%** of the margin: 2.14 of the
      7.00 we make on a 100.00 cost.
    - :func:`violates_margin_floor` did not bound it. The floor is evaluated
      against ``current`` before this function runs (``quote.price_for``), and
      the price actually charged was never re-checked — so at a floor-level
      markup the sale went *negative*. Cost 100.00 with ``b2b_markup_pct = 2``
      prices at 102.00, clearing a 2% floor exactly, and a merchant sending
      99.96 (drift exactly 2.0%) was charged **below our cost**.
    - It needed no adversary. A well-meaning client that caches the catalog
      does the same thing whenever our price ticks up, and the asymmetry means
      a stale-*high* quote cost us nothing while a stale-*low* one cost us the
      difference, every time.
    - Nothing recorded it. ``expected_price`` reaches only the *rejection*
      body and the request digest; a placed order stores the charged price and
      neither our price at that moment nor theirs, so the loss was
      unmeasurable after the fact.

    The band is still worth keeping, which is why it stayed: it stops an order
    failing over a cent of genuine drift, and the merchant remains protected —
    they never pay more than :data:`PRICE_DRIFT_TOLERANCE_PCT` above the price
    they last read, and a rejection hands them our exact current price to
    re-quote against.

    Args:
        current: Our price for this merchant — :func:`merchant_price`'s
            result. A non-positive value is refused rather than divided by.
        expected: The price the merchant sent, as they last read it. It
            decides whether the order proceeds; it never decides what it
            costs.

    Returns:
        ``current`` when the drift is inside the band, or ``None`` when it is
        outside — and for a non-positive ``current``, which is not a price.
    """
    if current <= _ZERO:
        # The caller's margin floor already refuses a zero or negative price,
        # so this is unreachable through the order path — but ``current`` is
        # the denominator below, and a documented precondition that nothing
        # enforces is one refactor away from a ZeroDivisionError on the money
        # path. Refusing reads as ``price_changed``, which is the right answer
        # for a price we cannot quote.
        return None
    drift = abs(current - expected) / current * _HUNDRED
    if drift > PRICE_DRIFT_TOLERANCE_PCT:
        return None
    return current


__all__ = [
    "PRICE_DRIFT_TOLERANCE_PCT",
    "effective_cost",
    "merchant_markup_pct",
    "merchant_price",
    "price_to_charge",
    "violates_margin_floor",
]
