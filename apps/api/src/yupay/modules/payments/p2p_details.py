"""The transfer instructions behind a pending ``p2p`` payment (ADR-0097).

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
from yupay.modules.p2p.cards import open_pan
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.payments.models import Payment
from yupay.modules.payments.schemas import P2PPaymentDetailsOut, PaymentOut

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


async def payment_out(db: AsyncSession, payment: Payment) -> PaymentOut:
    """``PaymentOut`` for the customer routes: the payment plus, for a pending
    ``p2p`` one, where to send the money."""
    out = PaymentOut.model_validate(payment)
    out.p2p = await p2p_details(db, payment)
    return out


__all__ = ["p2p_details", "payment_out"]
