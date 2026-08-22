"""Create a wallet-funding order and payment intent (ADR-0058).

Does not credit the ledger — that happens in ``payments`` settlement so the
acquirer webhook stays the only success path.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import ORDER_EXPIRY_SECONDS, Actor, _record_event
from yupay.modules.payments.models import Payment
from yupay.modules.wallet.topup_limits import (
    PURPOSE_WALLET_TOPUP,
    assert_provider_matches_surface,
    currency_for_provider,
    quantize_topup_amount,
)


async def _existing_topup_order(
    db: AsyncSession, *, user_id: str, idempotency_key: str
) -> Order | None:
    stmt = select(Order).where(
        Order.user_id == user_id,
        Order.idempotency_key == idempotency_key,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_topup(
    db: AsyncSession,
    *,
    user_id: str,
    amount: Decimal,
    provider: str,
    idempotency_key: str,
    source: str,
    return_url: str | None = None,
) -> Payment:
    """Insert a ``wallet_topup`` order (no SKUs) and create a payment intent.

    Replay of the same ``idempotency_key`` returns the original payment.
    """
    currency = currency_for_provider(provider)
    assert_provider_matches_surface(provider, source)
    charged = quantize_topup_amount(amount, currency)

    existing = await _existing_topup_order(db, user_id=user_id, idempotency_key=idempotency_key)
    if existing is not None:
        # A replay must be the *same* request. Checking only the purpose meant a
        # client reusing a stale key for a different amount got a hosted
        # checkout for the old one — money moving on a figure nobody asked for.
        # `payments._validate_intent_replay` holds the same line for intents.
        if (
            existing.purpose != PURPOSE_WALLET_TOPUP
            or existing.currency != currency
            or existing.total_charged != charged
        ):
            raise ConflictError(
                "Idempotency-Key was already used for a different request",
                extra={"order_id": existing.id},
            )
        return await _payment_for_order(db, existing.id)

    created = now()
    order_id = new_id()
    actor = Actor(user_id=user_id, email=None)
    order = Order(
        id=order_id,
        user_id=user_id,
        guest_email=None,
        status="pending_payment",
        currency=currency,
        total_usd=Decimal("0"),
        total_charged=charged,
        fx_snapshot_id=None,
        expires_at=created + timedelta(seconds=ORDER_EXPIRY_SECONDS),
        idempotency_key=idempotency_key,
        source=source,
        purpose=PURPOSE_WALLET_TOPUP,
    )
    try:
        async with db.begin_nested():
            db.add(order)
            _record_event(
                db,
                order_id=order_id,
                kind="order.created",
                actor=actor,
                payload={
                    "purpose": PURPOSE_WALLET_TOPUP,
                    "currency": currency,
                    "total_charged": str(charged),
                    "provider": provider,
                },
            )
            await db.flush()
    except IntegrityError as exc:
        replay = await _existing_topup_order(db, user_id=user_id, idempotency_key=idempotency_key)
        if replay is not None:
            return await _payment_for_order(db, replay.id)
        raise ConflictError("order conflict") from exc

    from yupay.modules.payments import service as pay_svc

    return await pay_svc.create_intent(
        db,
        order_id=order_id,
        provider=provider,
        return_url=return_url,
        idempotency_key=f"pay:{idempotency_key}",
    )


async def _payment_for_order(db: AsyncSession, order_id: str) -> Payment:
    from yupay.modules.payments import service as pay_svc

    payment = await pay_svc.get_active_payment(db, order_id)
    if payment is not None:
        return payment
    # Already settled (replay after success): return the succeeded row.
    stmt = (
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        raise ConflictError("top-up order has no payment yet; retry")
    return payment
