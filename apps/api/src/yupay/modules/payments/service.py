"""Payment service: intent creation, webhook handling, FSM transitions.

All side effects on the order's status go through :func:`_mark_payment_succeeded` —
the only place that flips ``orders.status`` to ``paid``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.payments.gateways import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentNotIntegratedError,
    WebhookEvent,
    get_gateway,
)
from yupay.modules.payments.models import Payment, PaymentAttempt, PaymentWebhook
from yupay.modules.wallet import api as wallet_api

log = get_logger("yupay.payments.service")


def _record_attempt(
    db: AsyncSession,
    *,
    payment_id: str,
    kind: str,
    status: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    db.add(
        PaymentAttempt(
            id=new_id(),
            payment_id=payment_id,
            kind=kind,
            status=status,
            payload=payload or {},
            error=error,
        )
    )


async def _load_order(db: AsyncSession, order_id: str) -> Order:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .where(Order.id == order_id)
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    return order


async def _find_active_payment(db: AsyncSession, order_id: str) -> Payment | None:
    """Return the currently-active payment for an order, if any."""
    stmt = (
        select(Payment)
        .options(selectinload(Payment.attempts))
        .where(
            Payment.order_id == order_id,
            Payment.status.in_(("pending", "requires_action")),
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_intent(
    db: AsyncSession,
    *,
    order_id: str,
    provider: str,
    return_url: str | None,
) -> Payment:
    """Create or reuse a payment intent for ``order_id`` via ``provider``."""
    order = await _load_order(db, order_id)
    if order.status != "pending_payment":
        raise ConflictError(
            "order is not awaiting payment", extra={"status": order.status}
        )

    gw = get_gateway(provider)
    if not gw.available:
        raise ConflictError(
            "payment provider not available",
            extra={"provider": gw.provider},
        )

    # Reuse the pending payment for this order — one intent at a time.
    existing = await _find_active_payment(db, order.id)
    if existing is not None and existing.provider == gw.provider:
        return existing
    if existing is not None and existing.provider != gw.provider:
        raise ConflictError(
            "an active payment already exists for this order with a different provider",
            extra={"current_provider": existing.provider},
        )

    payment_id = new_id()
    try:
        intent = await gw.create_intent(
            order=order, return_url=return_url or "https://yupay.io/checkout/return"
        )
    except (PaymentGatewayError, PaymentNotIntegratedError) as exc:
        log.warning("payments.create_intent.failed", provider=provider, error=str(exc))
        raise ConflictError("payment provider rejected the request") from exc

    payment = Payment(
        id=payment_id,
        order_id=order.id,
        provider=gw.provider,
        status=intent.status,
        amount=order.total_charged,
        currency=order.currency,
        intent_url=intent.intent_url,
        external_id=intent.external_id,
        extra_metadata=intent.extra_metadata,
    )
    db.add(payment)
    _record_attempt(
        db,
        payment_id=payment_id,
        kind="create_intent",
        status="ok",
        payload={
            "external_id": intent.external_id,
            "intent_url": intent.intent_url,
            "metadata": intent.extra_metadata,
        },
    )
    await db.flush()
    return payment


async def _mark_payment_succeeded(
    db: AsyncSession, *, payment: Payment, event: WebhookEvent
) -> None:
    """Single-spot transition: payment → succeeded and order → paid."""
    moment = now()
    payment.status = "succeeded"
    payment.succeeded_at = moment
    payment.updated_at = moment

    order = (
        await db.execute(select(Order).where(Order.id == payment.order_id))
    ).scalar_one()

    if order.status == "pending_payment":
        order.status = "paid"
        order.paid_at = moment
        order.updated_at = moment
        db.add(
            OrderEvent(
                id=new_id(),
                order_id=order.id,
                kind="order.paid",
                payload={
                    "payment_id": payment.id,
                    "provider": payment.provider,
                    "external_event_id": event.external_event_id,
                },
                actor="payments",
            )
        )
        # Synchronous saga (ADR-0013). Will move to an outbox/Dramatiq actor once
        # the worker is wired up — the public service signature stays the same.
        from yupay.modules.fulfillment import service as fulfillment_svc  # noqa: PLC0415

        await db.flush()
        await fulfillment_svc.start_for_order(db, order_id=order.id)


async def _mark_payment_terminal(
    db: AsyncSession,
    *,
    payment: Payment,
    event: WebhookEvent,
    new_status: str,
) -> None:
    moment = now()
    payment.status = new_status
    payment.updated_at = moment
    if new_status == "failed":
        payment.failed_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=payment.order_id,
            kind=f"payment.{new_status}",
            payload={
                "payment_id": payment.id,
                "provider": payment.provider,
                "external_event_id": event.external_event_id,
            },
            actor="payments",
        )
    )


async def handle_webhook(
    db: AsyncSession,
    *,
    provider: str,
    headers: Mapping[str, str],
    body: bytes,
) -> Payment | None:
    """Verify, dedup, and process a provider webhook.

    Returns the payment that was updated, or ``None`` if the event was a duplicate.
    Raises ``ValidationError`` on a bad signature so the route can answer 400.
    """
    gw = get_gateway(provider)
    try:
        event = await gw.verify_webhook(headers=headers, body=body)
    except (PaymentGatewayError, PaymentNotIntegratedError) as exc:
        # Persist the rejection so we can audit signature-mismatch attacks later.
        db.add(
            PaymentWebhook(
                id=new_id(),
                provider=gw.provider,
                external_event_id=f"rejected:{new_id()}",
                payload={"body": body.decode("utf-8", errors="replace")},
                signature_ok=False,
            )
        )
        raise ValidationError(
            "webhook signature or shape verification failed",
            extra={"provider": gw.provider, "reason": str(exc)},
        ) from exc

    # Idempotency: rely on the partial unique on (provider, external_event_id).
    db.add(
        PaymentWebhook(
            id=new_id(),
            provider=gw.provider,
            external_event_id=event.external_event_id,
            payload=event.raw,
            signature_ok=True,
            processed_at=now(),
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        log.info(
            "payments.webhook.duplicate",
            provider=provider,
            external_event_id=event.external_event_id,
        )
        return None

    if event.external_payment_id is None:
        raise ValidationError("webhook event has no payment reference")
    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.provider == gw.provider)
            .where(Payment.external_id == event.external_payment_id)
        )
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError(
            "no payment matched the webhook",
            extra={"provider": gw.provider, "external_id": event.external_payment_id},
        )

    _record_attempt(
        db,
        payment_id=payment.id,
        kind="webhook",
        status="ok",
        payload={
            "outcome": event.outcome,
            "external_event_id": event.external_event_id,
        },
    )

    if event.outcome == "succeeded":
        await _mark_payment_succeeded(db, payment=payment, event=event)
    elif event.outcome == "failed":
        await _mark_payment_terminal(db, payment=payment, event=event, new_status="failed")
    elif event.outcome == "cancelled":
        await _mark_payment_terminal(
            db, payment=payment, event=event, new_status="cancelled"
        )

    await db.flush()
    return payment


async def simulate_webhook(
    db: AsyncSession,
    *,
    payment_id: str,
    outcome: str,
) -> Payment:
    """Admin-only dev helper. Synthesises a webhook for the given payment."""
    payment = (
        await db.execute(
            select(Payment)
            .options(selectinload(Payment.attempts))
            .where(Payment.id == payment_id)
        )
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    if payment.status not in ("pending", "requires_action"):
        raise ConflictError(
            "payment is not in a state that can be webhook-driven",
            extra={"status": payment.status},
        )
    if payment.provider != "mock":
        raise ConflictError(
            "simulate-webhook is only supported for the mock provider",
            extra={"provider": payment.provider},
        )

    import json  # noqa: PLC0415 -- keep the dev helper self-contained

    body = json.dumps(
        {
            "event_id": f"sim_{new_id()}",
            "payment_id": payment.external_id,
            "outcome": outcome,
        }
    ).encode("utf-8")
    return await handle_webhook(
        db, provider=payment.provider, headers={}, body=body
    ) or payment


async def get_payment(db: AsyncSession, payment_id: str) -> Payment:
    stmt = (
        select(Payment)
        .options(selectinload(Payment.attempts))
        .where(Payment.id == payment_id)
    )
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    return payment


async def refund_admin(
    db: AsyncSession,
    *,
    payment_id: str,
    admin_id: str,
    amount: Decimal | None = None,
    reason: str | None = None,
) -> Payment:
    """Admin-initiated refund.

    Calls the gateway's ``refund`` hook (if implemented), flips the payment to
    ``refunded`` / ``partially_refunded``, walks the order to ``refunded``, and
    posts a double-entry on the ledger:

      D house_refunds  amount
      C provider_clearing:<provider>  amount

    ``amount`` defaults to the full charged amount. The skeleton treats any
    ``amount < payment.amount`` as a partial refund — it does not currently
    track cumulative refunds, so calling refund_admin twice on the same
    payment is rejected. Add a ``payment_refunds`` row if you need that.
    """
    payment = await get_payment(db, payment_id)
    if payment.status not in ("succeeded", "partially_refunded"):
        raise ConflictError(
            "payment can't be refunded in its current state",
            extra={"status": payment.status},
        )
    refund_amount = amount if amount is not None else payment.amount
    if refund_amount <= 0:
        raise ValidationError("refund amount must be positive")
    if refund_amount > payment.amount:
        raise ValidationError(
            "refund amount exceeds payment amount",
            extra={"amount": str(refund_amount), "max": str(payment.amount)},
        )

    gw = get_gateway(payment.provider)
    moment = now()
    refund_metadata: dict[str, Any] = {
        "refund_amount": str(refund_amount),
        "reason": reason or "",
        "admin_id": admin_id,
    }

    if gw.available:
        try:
            result = await gw.refund(payment=payment, amount=refund_amount)
            refund_metadata["external_refund_id"] = result.external_refund_id
            refund_metadata.update(result.extra_metadata)
        except (PaymentGatewayError, PaymentNotIntegratedError) as exc:
            _record_attempt(
                db,
                payment_id=payment.id,
                kind="refund",
                status="error",
                payload=refund_metadata,
                error=str(exc),
            )
            await db.flush()
            raise ConflictError(
                "payment provider rejected the refund",
                extra={"reason": str(exc)},
            ) from exc
    else:
        # Stubbed provider — record the intent but skip the network call.
        refund_metadata["dry_run"] = True

    is_full = refund_amount == payment.amount
    payment.status = "refunded" if is_full else "partially_refunded"
    payment.updated_at = moment
    payment.extra_metadata = {**payment.extra_metadata, "last_refund": refund_metadata}

    _record_attempt(
        db,
        payment_id=payment.id,
        kind="refund",
        status="ok",
        payload=refund_metadata,
    )

    # Order: mark refunded only for a full refund. Partial refunds keep the
    # original status — they're an accounting concern, not an FSM concern.
    order = (
        await db.execute(select(Order).where(Order.id == payment.order_id))
    ).scalar_one()
    if is_full and order.status != "refunded":
        order.status = "refunded"
        order.updated_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="payment.refunded",
            payload={
                "payment_id": payment.id,
                "provider": payment.provider,
                "amount": str(refund_amount),
                "full": is_full,
                "reason": reason or "",
            },
            actor=f"admin:{admin_id}",
        )
    )

    # Ledger: book the refund through the wallet module.
    house_refunds = await wallet_api.ensure_account(
        db,
        owner_type="house",
        owner_id="house",
        kind="house_refunds",
        currency=payment.currency,
    )
    provider_clearing = await wallet_api.ensure_account(
        db,
        owner_type="provider",
        owner_id=payment.provider,
        kind="provider_clearing",
        currency=payment.currency,
    )
    await wallet_api.post(
        db,
        kind="payment.refund",
        legs=[
            wallet_api.Leg(
                account_id=house_refunds.id,
                direction="D",
                amount=refund_amount,
                currency=payment.currency,
            ),
            wallet_api.Leg(
                account_id=provider_clearing.id,
                direction="C",
                amount=refund_amount,
                currency=payment.currency,
            ),
        ],
        idempotency_key=f"refund:{payment.id}",
        reference=wallet_api.Reference(type="payment", id=payment.id),
        actor=f"admin:{admin_id}",
        metadata={"reason": reason or "", "full": is_full},
    )

    await db.flush()
    log.info(
        "payments.refund.ok",
        payment_id=payment.id,
        provider=payment.provider,
        amount=str(refund_amount),
        full=is_full,
    )
    return payment


async def list_webhooks_admin(
    db: AsyncSession,
    *,
    provider: str | None = None,
    signature_ok: bool | None = None,
    limit: int = 50,
) -> list[PaymentWebhook]:
    """Admin listing of received webhooks for the audit / debugging page."""
    stmt = (
        select(PaymentWebhook)
        .order_by(PaymentWebhook.received_at.desc())
        .limit(limit)
    )
    if provider is not None:
        stmt = stmt.where(PaymentWebhook.provider == provider)
    if signature_ok is not None:
        stmt = stmt.where(PaymentWebhook.signature_ok.is_(signature_ok))
    return list((await db.execute(stmt)).scalars().all())


async def list_payments_admin(
    db: AsyncSession,
    *,
    order_id: str | None = None,
    provider: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[Payment]:
    stmt = (
        select(Payment)
        .options(selectinload(Payment.attempts))
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    if order_id is not None:
        stmt = stmt.where(Payment.order_id == order_id)
    if provider is not None:
        stmt = stmt.where(Payment.provider == provider)
    if status_filter is not None:
        stmt = stmt.where(Payment.status == status_filter)
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "create_intent",
    "get_payment",
    "handle_webhook",
    "list_payments_admin",
    "list_webhooks_admin",
    "refund_admin",
    "simulate_webhook",
]


# Defensive: silence unused-import linters; ``Decimal``/``datetime`` are referenced via
# type hints in serialised payloads but never accessed at runtime here.
_ = Decimal, datetime
