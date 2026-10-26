"""An operator's permission for a provider to cancel a payment after delivery.

Paynet's ``CancelTransaction`` — and Payme's and Uzum's cancels — is refused
once any goods have shipped: the provider cannot tell a customer with a working code from one
without, and clawing the money back would hand the goods over for free. But
sometimes the goods did not really arrive — a dead promo code, currency the
supplier reported as credited that never reached the account — and the only
way to give the money back to the payer's card without a manual transfer is
a cancel from the provider's own cabinet.

So the refusal stays the default, and an operator can lift it for one payment,
with a reason, from the order page. The permission is a fact on the payment
(``extra_metadata["cancel_allowed"]``: who, when, why) and an event on the
order timeline; the provider's cancel then runs the ordinary reversal.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.modules.orders.models import OrderEvent
from yupay.modules.payments.models import Payment

CANCEL_ALLOWED_KEY: Final = "cancel_allowed"

#: Providers whose cancel arrives from their side and is guarded by delivery.
#: Click sends no cancel at all — its refunds are recorded by hand instead
#: (:func:`record_cabinet_refund`).
PROVIDERS: Final = frozenset({"paynet", "payme", "uzum"})

#: Providers that refund only from their own cabinet and never tell us.
CABINET_ONLY: Final = frozenset({"click", "click_miniapp"})


def cancel_allowed(payment: Payment) -> bool:
    """``True`` when an operator has allowed the provider to cancel this payment."""
    return bool((payment.extra_metadata or {}).get(CANCEL_ALLOWED_KEY))


async def allow_cancel(db: AsyncSession, *, payment_id: str, admin_id: str, reason: str) -> Payment:
    """Let the provider cancel a delivered payment, once, on an operator's word.

    Idempotent: a second call on an allowed payment changes nothing.

    Args:
        db: Active session; the caller commits.
        payment_id: The payment to unlock.
        admin_id: Who decided, for the audit trail.
        reason: Why the goods did not reach the customer.

    Returns:
        The payment.

    Raises:
        NotFoundError: No such payment.
        ConflictError: The provider cancels nothing on its side, or the payment
            is not ``succeeded`` (nothing to cancel, or already refunded).
    """
    payment = (
        await db.execute(select(Payment).where(Payment.id == payment_id).with_for_update())
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    if payment.provider not in PROVIDERS:
        raise ConflictError(
            "this provider does not cancel payments from its side",
            reason="provider",
            extra={"provider": payment.provider},
        )
    if payment.status != "succeeded":
        raise ConflictError(
            "only a succeeded payment can be cancelled",
            reason="status",
            extra={"status": payment.status},
        )
    if cancel_allowed(payment):
        return payment

    grant: dict[str, Any] = {"by": f"admin:{admin_id}", "at": now().isoformat(), "reason": reason}
    payment.extra_metadata = {**(payment.extra_metadata or {}), CANCEL_ALLOWED_KEY: grant}
    payment.updated_at = now()
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=payment.order_id,
            kind="admin.provider_cancel_allowed",
            payload={"payment_id": payment.id, "provider": payment.provider, "reason": reason},
            actor=f"admin:{admin_id}",
        )
    )
    await db.flush()
    return payment


async def record_cabinet_refund(
    db: AsyncSession,
    *,
    payment_id: str,
    admin_id: str,
    reason: str,
    provider_reference: str,
) -> Payment:
    """Book a refund an operator already made in Click's cabinet.

    Click sends no callback for a refund, so without this the order stays paid
    and the ledger keeps money that went back to the card. This runs the same
    reversal a provider cancel does — payment and order to ``refunded``, the
    ledger posting, open tasks cancelled — and moves no money itself.

    Args:
        db: Active session; the caller commits.
        payment_id: The Click payment that was refunded.
        admin_id: Who recorded it.
        reason: Why the money went back.
        provider_reference: The refund's id in Click's cabinet — the evidence.

    Returns:
        The payment, now ``refunded``.

    Raises:
        NotFoundError: No such payment.
        ConflictError: Not a cabinet-only provider, not ``succeeded``, or a
            supplier or a CS2 skin trade is still working on the order.
    """
    from yupay.modules.payments import service as pay_svc
    from yupay.modules.skins.refund_guard import skin_trade_in_flight

    payment = (
        await db.execute(select(Payment).where(Payment.id == payment_id).with_for_update())
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    if payment.provider not in CABINET_ONLY:
        raise ConflictError(
            "this provider refunds through its own cancel, not by hand",
            reason="provider",
            extra={"provider": payment.provider},
        )
    if payment.status != "succeeded":
        raise ConflictError(
            "only a succeeded payment can be refunded",
            reason="status",
            extra={"status": payment.status},
        )
    if await skin_trade_in_flight(db, payment.order_id):
        raise ConflictError(
            "a CS2 skin on this order is still being bought or sent; "
            "wait until it is received or fails",
            reason="skin_trade_in_flight",
        )
    await pay_svc.refuse_while_a_supplier_works(db, payment.order_id)

    actor = f"admin:{admin_id}"
    record: dict[str, Any] = {
        "refund_amount": str(payment.amount),
        "reason": reason,
        "admin_id": admin_id,
        "refunded_to": "card",
        "provider_reference": provider_reference,
    }
    payment.extra_metadata = {**(payment.extra_metadata or {}), "last_refund": record}
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=payment.order_id,
            kind="admin.cabinet_refund_recorded",
            payload={"payment_id": payment.id, "provider": payment.provider, **record},
            actor=actor,
        )
    )
    # Flushed first: the reversal refreshes the row and would drop this write.
    await db.flush()
    await pay_svc.reverse_provider_payment(
        db,
        payment=payment,
        external_event_id=f"admin-cabinet-refund:{provider_reference}",
        actor=actor,
    )
    return payment


__all__ = [
    "CABINET_ONLY",
    "CANCEL_ALLOWED_KEY",
    "PROVIDERS",
    "allow_cancel",
    "cancel_allowed",
    "record_cabinet_refund",
]
