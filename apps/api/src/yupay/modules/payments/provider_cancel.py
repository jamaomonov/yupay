"""An operator's permission for a provider to cancel a payment after delivery.

Paynet's ``CancelTransaction`` is refused with ``306`` once any goods have
shipped: the provider cannot tell a customer with a working code from one
without, and clawing the money back would hand the goods over for free. But
sometimes the goods did not really arrive — a dead promo code, currency the
supplier reported as credited that never reached the account — and the only
way to give the money back to the payer's card without a manual transfer is
a cancel from Paynet's own cabinet.

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

#: Providers whose cancel is initiated on their side and guarded by delivery.
#: Payme has the same guard but no cabinet cancel in use, so it is not here.
PROVIDERS: Final = frozenset({"paynet"})


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


__all__ = ["CANCEL_ALLOWED_KEY", "PROVIDERS", "allow_cancel", "cancel_allowed"]
