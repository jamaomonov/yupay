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

    Spec §8.4, implemented as written: drift within ±:data:`PRICE_DRIFT_TOLERANCE_PCT`
    executes at the **lower** of the two; anything beyond it is a
    ``price_changed`` rejection carrying our current price. This function is
    the rule's single home — the order path calls it and decides nothing about
    drift on its own, so changing the policy is a change here and nowhere else.

    **Known and deliberate, recorded so nobody has to rediscover it.** A
    merchant can fetch ``/catalog`` — live-computed, never cached — immediately
    before ordering and then always send ``expected_price = current × 0.98``,
    taking a guaranteed 2% off wholesale on every order. On the default 7%
    markup that is roughly a quarter of the margin, and the margin floor does
    not catch it: 7% − 2% still clears the 2% floor. The rule came from the
    Steam-gifts flow, where the counterparty is a human who cannot compute
    that; a merchant's counterparty is a machine that can. It has been raised
    with the owner. Until they rule otherwise the spec governs, and this is
    the one line that changes when they do — e.g. ``return current`` for
    "quote-only", or an asymmetric band that accepts a higher expectation and
    refuses a lower one.

    Args:
        current: Our price for this merchant — :func:`merchant_price`'s
            result. Must be positive; it is the denominator of the drift.
        expected: The price the merchant sent, as they last read it.

    Returns:
        The price to charge, or ``None`` when the drift is outside the band.
    """
    drift = abs(current - expected) / current * _HUNDRED
    if drift > PRICE_DRIFT_TOLERANCE_PCT:
        return None
    return min(current, expected)


__all__ = [
    "PRICE_DRIFT_TOLERANCE_PCT",
    "effective_cost",
    "merchant_markup_pct",
    "merchant_price",
    "price_to_charge",
    "violates_margin_floor",
]
