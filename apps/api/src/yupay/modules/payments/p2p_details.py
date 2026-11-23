"""What a pending payment shows the payer: a ``p2p`` transfer (ADR-0097), a ``uzqr`` QR (ADR-0106).

The gateway stores only the reservation number on the payment; the card
number stays sealed in ``p2p_cards`` and is opened here, on read, for the
payer — the same way the reseller cabinet opens it for a deposit. Nothing is
written: a payment that is no longer pending, or whose reservation has
closed, simply carries no instructions.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.orders.models import Order
from yupay.modules.p2p.cards import open_pan
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.payments.models import Payment
from yupay.modules.payments.schemas import (
    P2PPaymentDetailsOut,
    PaymentOut,
    UzqrPaymentDetailsOut,
)

_PREFIX = "p2p:"


def _grouped(pan: str) -> str:
    return " ".join(pan[i : i + 4] for i in range(0, len(pan), 4))


async def p2p_details(db: AsyncSession, payment: Payment) -> P2PPaymentDetailsOut | None:
    """Instructions for ``payment``, or ``None`` when there is nothing to transfer."""
    if payment.provider != "p2p" or payment.status != "pending":
        return None
    external = payment.external_id or ""
    if not external.startswith(_PREFIX):
        return None
    reservation = await db.scalar(
        select(P2PReservation).where(P2PReservation.number == external[len(_PREFIX) :])
    )
    if reservation is None or reservation.status != "pending" or reservation.expires_at <= now():
        return None
    card = await db.get(P2PCard, reservation.card_id)
    if card is None:
        return None
    return P2PPaymentDetailsOut(
        reservation_number=reservation.number,
        pan=_grouped(open_pan(card)),
        holder_name=card.holder_name,
        network=card.network,
        amount_uzs=reservation.amount_uzs,
        expires_at=reservation.expires_at,
    )


async def uzqr_details(db: AsyncSession, payment: Payment) -> UzqrPaymentDetailsOut | None:
    """The QR for a pending ``uzqr`` payment (ADR-0106), or ``None``.

    Hidden once the order's window has closed: the scheduler is about to
    cancel the invoice, and a QR shown past that point is one the bank app
    will refuse.
    """
    if payment.provider != "uzqr" or payment.status != "pending":
        return None
    meta = payment.extra_metadata or {}
    invoice_id, qr_text = meta.get("invoice_id"), meta.get("qr_text")
    if not isinstance(invoice_id, str) or not isinstance(qr_text, str):
        return None
    order = await db.get(Order, payment.order_id)
    if order is None or order.status != "pending_payment" or order.expires_at <= now():
        return None
    return UzqrPaymentDetailsOut(
        invoice_id=invoice_id,
        qr_text=qr_text,
        amount=payment.amount,
        expires_at=order.expires_at,
    )


async def payment_out(db: AsyncSession, payment: Payment) -> PaymentOut:
    """``PaymentOut`` for the customer routes: the payment plus, for a pending
    ``p2p`` one, where to send the money, and for a pending ``uzqr`` one, the
    QR to scan."""
    out = PaymentOut.model_validate(payment)
    out.p2p = await p2p_details(db, payment)
    out.uzqr = await uzqr_details(db, payment)
    return out


__all__ = ["p2p_details", "payment_out", "uzqr_details"]
