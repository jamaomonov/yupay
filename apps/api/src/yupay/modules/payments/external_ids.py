"""A payment's ``external_id`` that no earlier payment of the provider already holds.

Payme, Uzum and Click key a payment by order (``payme:<order>``). A buyer whose card was
declined tries again on the same order: the cancelled payment keeps that id, and a new
one with the same id broke ``uq_payments_provider_external`` — the acquirer got a system
error and showed the buyer «Сервис поставщика услуг недоступен» (prod 2026-09-29, 19
times in a week on Payme alone). Their callbacks find a payment through their own
transaction rows, never by this id, so a suffix on a retry is safe.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.payments.models import Payment


async def unclaimed_external_id(
    db: AsyncSession, *, provider: str, external_id: str, payment_id: str
) -> str:
    """``external_id`` for the first attempt, ``<external_id>:<payment_id>`` after.

    Args:
        db: Session.
        provider: The payment's provider.
        external_id: The id the gateway would use (``payme:<order>``).
        payment_id: The new payment's id, for the suffix.
    """
    taken = (
        await db.execute(
            select(Payment.id).where(
                Payment.provider == provider, Payment.external_id == external_id
            )
        )
    ).first()
    return external_id if taken is None else f"{external_id}:{payment_id}"


__all__ = ["unclaimed_external_id"]
