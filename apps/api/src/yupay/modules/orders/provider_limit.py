"""Per-provider spend limit: how much one buyer may pay through a kassa before review.

The owner's rule of 2026-10-21, for Click's mini-app kassa: past 90 000 soʻm a buyer's
payment goes to an operator instead of to the supplier. The number lives in the admin
(``payments.PaymentReviewLimit``), one row per payment slug, so it can move without a deploy.

**A limit on one payment is a limit a carder splits.** Learn that the bar is 80 000 and pay
50 000 twice. So the rule sums the buyer's settled payments through the same slug over a
trailing window (24 h by default, also in the admin), this payment included, and holds the
order whose payment carries the sum past the limit — and every one after it, because a held
order's payment has settled and stays in the sum.

"The buyer" is linked the way the risk module links one (``orders.risk``), minus the IP:

- the signed-in account, or the guest email;
- the device fingerprint, when ``risk_device_identity`` is on (ADR-0062);
- the delivery target — the player id, the Telegram handle — so a second account buying for
  the same recipient still adds up.

The IP is left out on purpose. A whole mobile carrier sits behind a handful of addresses
here, and a sum keyed on one would add strangers' purchases together and hold honest buyers
for spending they never did. The window rules in ``risk`` can afford it — they count
orders, and a stranger's order is one more — but a sum against a fixed limit cannot.

Wallet top-ups count and are held too: otherwise the limit is one top-up of the balance
away from not existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, Text, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.risk import targets_from
from yupay.modules.payments.models import Payment, PaymentReviewLimit


@dataclass(frozen=True)
class LimitTrip:
    """A buyer past a provider's limit — what the hold records and the alert says."""

    provider: str
    window_total: Decimal
    max_amount: Decimal
    currency: str
    window_hours: int
    linked_payments: int


async def _settled_payment(db: AsyncSession, order_id: str) -> Payment | None:
    """The order's settled payment — the one this settlement just recorded."""
    return (
        await db.execute(
            select(Payment)
            .where(Payment.order_id == order_id, Payment.status == "succeeded")
            .order_by(Payment.succeeded_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _same_buyer(db: AsyncSession, order: Order) -> ColumnElement[bool] | None:
    """A condition on ``Order`` matching the same buyer: account, email, device or recipient.

    ``None`` when the order carries nothing to link on — then only its own payment counts.
    """
    predicates = []
    if order.user_id is not None:
        predicates.append(Order.user_id == order.user_id)
    if order.guest_email:
        predicates.append(Order.guest_email == order.guest_email.lower())
    if get_settings().risk_device_identity:
        device = (
            await db.execute(
                select(OrderEvidence.device_hash).where(OrderEvidence.order_id == order.id)
            )
        ).scalar_one_or_none()
        if device:
            predicates.append(
                Order.id.in_(
                    select(OrderEvidence.order_id).where(OrderEvidence.device_hash == device)
                )
            )

    targets: set[str] = set()
    for data in (
        await db.execute(select(OrderItem.fulfillment_data).where(OrderItem.order_id == order.id))
    ).scalars():
        targets.update(targets_from(data or {}))
    if targets:
        # The same normalisation as ``targets_from``, in SQL — see the matching
        # query in ``risk._gather``.
        predicates.append(
            Order.id.in_(
                select(OrderItem.order_id).where(
                    text(
                        "EXISTS (SELECT 1 FROM jsonb_each_text(order_items.fulfillment_data) kv"
                        " WHERE lower(ltrim(btrim(kv.value), '@')) = ANY(:targets))"
                    ).bindparams(bindparam("targets", value=sorted(targets), type_=ARRAY(Text)))
                )
            )
        )
    return or_(*predicates) if predicates else None


async def check(db: AsyncSession, order: Order) -> LimitTrip | None:
    """Whether this order's payment carries its buyer past the provider's limit.

    Args:
        db: Session inside the settlement transaction.
        order: The order whose payment just settled.

    Returns:
        A :class:`LimitTrip` to hold the order with, or ``None`` when its provider has no
        enabled limit, the payment is in another currency, or the window stays within it.
    """
    payment = await _settled_payment(db, order.id)
    if payment is None:
        return None
    limit = await db.get(PaymentReviewLimit, payment.provider)
    if limit is None or not limit.enabled or payment.currency != limit.currency:
        return None

    since = now() - timedelta(hours=limit.window_hours)
    same_buyer = await _same_buyer(db, order)
    earlier, count = Decimal("0"), 0
    if same_buyer is not None:
        row = (
            await db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0), func.count())
                .select_from(Payment)
                .join(Order, Order.id == Payment.order_id)
                .where(
                    Payment.provider == payment.provider,
                    Payment.status == "succeeded",
                    Payment.currency == limit.currency,
                    Payment.succeeded_at >= since,
                    Payment.id != payment.id,
                    same_buyer,
                )
            )
        ).one()
        earlier, count = Decimal(row[0]), int(row[1])

    total = earlier + payment.amount
    if total <= limit.max_amount:
        return None
    return LimitTrip(
        provider=payment.provider,
        window_total=total,
        max_amount=limit.max_amount,
        currency=limit.currency,
        window_hours=limit.window_hours,
        linked_payments=count,
    )


__all__ = ["LimitTrip", "check"]
