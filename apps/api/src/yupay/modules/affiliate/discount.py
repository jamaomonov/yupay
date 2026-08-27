"""Whether an affiliate code applies to this buyer, and by how much.

Six conditions, all checked on the server, all again at order creation. The
client never sends a price — it does not today either — so the preview
endpoint's answer is for display only, and the authoritative arithmetic happens
here a second time when the order is actually created.

The rejection reasons are a closed set because the checkout UI branches on
them, and they are deliberately lossy in one place: a code that does not exist,
one that is switched off, and one whose partner is suspended all come back as
``"unknown"``. Distinguishing them would turn the preview endpoint into a
lookup service for other people's promo codes.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode, AffiliatePartner
from yupay.modules.orders.models import Order

#: Why a code was refused. The checkout UI shows a different message for each,
#: so these strings are a contract with the frontend, not a logging detail.
DiscountRejection = Literal[
    "unknown",
    "guest",
    "already_used",
    "not_first_order",
    "own_code",
    "pending_coded_order",
    "not_catalog",
]

#: Order states that mean the buyer has actually bought something before.
#: Deliberately not "any prior order": an abandoned unpaid cart must not cost
#: someone their one first-order discount forever.
_PAID_STATUSES = ("paid", "fulfilling", "delivered")

#: An order still waiting to be paid. One of these already carrying a code is
#: what ``pending_coded_order`` refuses against.
_OPEN_STATUSES = ("pending_payment",)

#: Smallest payable unit per currency, mirroring ``affiliate.ledger``. UZS has
#: no subunit in practice — Payme and Click both reject fractions.
_QUANTUM: dict[str, Decimal] = {"UZS": Decimal("1")}
_DEFAULT_QUANTUM = Decimal("0.01")

#: The precision ``order_items.discount_usd`` is stored at.
_USD_QUANTUM = Decimal("0.000001")


class ResolvedDiscount(BaseModel):
    """An affiliate code that applies to this buyer."""

    model_config = ConfigDict(frozen=True)

    code_id: str
    code: str
    percent: Decimal


def normalise(code: str) -> str:
    """Uppercase and strip, the way the codes are stored."""
    return code.strip().upper()


def discount_amount(total: Decimal, percent: Decimal, currency: str) -> Decimal:
    """The discount on ``total``, rounded to a payable amount.

    Args:
        total: The order total before the discount, in ``currency``.
        percent: The code's discount percentage, e.g. ``Decimal("7")``.
        currency: ISO-4217 code, used to pick the rounding quantum.

    Returns:
        The amount to take off, quantized so the buyer sees a whole number and
        the acquirers accept it.
    """
    quantum = _QUANTUM.get(currency.upper(), _DEFAULT_QUANTUM)
    return (total * percent / Decimal(100)).quantize(quantum, rounding=ROUND_HALF_UP)


async def resolve_code(
    db: AsyncSession, *, code: str, user_id: str | None, purpose: str
) -> ResolvedDiscount | DiscountRejection:
    """Decide whether ``code`` applies to this buyer.

    Args:
        db: Session.
        code: What the buyer typed; normalised here.
        user_id: The signed-in buyer, or ``None`` for a guest.
        purpose: The order's purpose — only ``catalog`` orders qualify.

    Returns:
        A :class:`ResolvedDiscount`, or one of :data:`DiscountRejection`.
    """
    # Cheap, local checks first, so a guest typing a code never touches the DB.
    if purpose != "catalog":
        return "not_catalog"
    if user_id is None:
        return "guest"

    row = (
        await db.execute(
            select(AffiliateCode, AffiliatePartner)
            .join(AffiliatePartner, AffiliatePartner.id == AffiliateCode.partner_id)
            .where(AffiliateCode.code == normalise(code))
        )
    ).first()
    if row is None:
        return "unknown"
    affiliate_code, partner = row
    if not affiliate_code.active or partner.status != "active":
        return "unknown"

    if partner.user_id is not None and partner.user_id == user_id:
        return "own_code"

    if await db.scalar(select(exists().where(AffiliateAttribution.user_id == user_id))):
        return "already_used"

    has_paid_order = await db.scalar(
        select(
            exists().where(
                Order.user_id == user_id,
                Order.purpose == "catalog",
                Order.status.in_(_PAID_STATUSES),
            )
        )
    )
    if has_paid_order:
        return "not_first_order"

    # Narrows the race described in the spec: without this a buyer could open
    # two orders carrying two different codes and pay both, taking two
    # discounts against one attribution.
    has_open_coded_order = await db.scalar(
        select(
            exists().where(
                Order.user_id == user_id,
                Order.affiliate_code_id.isnot(None),
                Order.status.in_(_OPEN_STATUSES),
            )
        )
    )
    if has_open_coded_order:
        return "pending_coded_order"

    return ResolvedDiscount(
        code_id=affiliate_code.id,
        code=affiliate_code.code,
        percent=affiliate_code.discount_percent,
    )


def distribute_discount_usd(line_totals_usd: list[Decimal], discount_usd: Decimal) -> list[Decimal]:
    """Split an order-level USD discount across its lines, proportionally.

    The rounding remainder goes to the largest line rather than being dropped,
    so the parts sum to exactly ``discount_usd``. A dropped remainder is money
    that silently reappears as margin. Most orders here are single-line, where
    this is the identity.

    Args:
        line_totals_usd: Each line's gross USD value, in order.
        discount_usd: The whole discount to distribute.

    Returns:
        One share per line, in the same order, summing to ``discount_usd``.
    """
    if not line_totals_usd:
        return []
    gross = sum(line_totals_usd, Decimal("0"))
    if gross <= 0:
        return [Decimal("0") for _ in line_totals_usd]

    shares = [
        (discount_usd * total / gross).quantize(_USD_QUANTUM, rounding=ROUND_HALF_UP)
        for total in line_totals_usd
    ]
    remainder = discount_usd - sum(shares, Decimal("0"))
    if remainder:
        biggest = line_totals_usd.index(max(line_totals_usd))
        shares[biggest] += remainder
    return shares


__all__ = [
    "DiscountRejection",
    "ResolvedDiscount",
    "discount_amount",
    "distribute_discount_usd",
    "normalise",
    "resolve_code",
]
