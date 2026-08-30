"""Payment service: intent creation, webhook handling, FSM transitions.

All side effects on the order's status go through :func:`_mark_payment_succeeded` —
the only place that flips ``orders.status`` to ``paid``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger

# Imported as the submodule rather than through ``affiliate.api``: that
# facade gains a router in a later step, and a router imported from here
# closes a cycle back through the v1 route stack.
from yupay.modules.affiliate import attribution as affiliate_attribution
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.payments import provider_state
from yupay.modules.payments.gateways import (
    PaymentGatewayError,
    PaymentNotIntegratedError,
    WebhookEvent,
    get_gateway,
)
from yupay.modules.payments.models import Payment, PaymentAttempt, PaymentWebhook
from yupay.modules.wallet import api as wallet_api

log = get_logger("yupay.payments.service")

# Cap on the raw body we persist for a rejected (signature/parse-failed)
# webhook. This route is reachable pre-auth, so an attacker could otherwise
# flood the audit table with arbitrarily large rows just by POSTing huge
# bodies that fail verification.
_REJECTED_WEBHOOK_BODY_CAP = 4096


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


async def _load_order(db: AsyncSession, order_id: str, *, for_update: bool = False) -> Order:
    stmt = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .where(Order.id == order_id)
    )
    if for_update:
        # ``FOR UPDATE`` on the order serialises concurrent
        # ``create_intent`` calls for the same order. The first one
        # walks the order to ``paid`` (or fails on its own); the
        # second one wakes up to a non-``pending_payment`` status and
        # is rejected by the ``ConflictError`` below. This is the
        # outer guarantee that we don't end up with two ``Payment``
        # rows / two wallet debits / two fulfilment kicks.
        stmt = stmt.with_for_update()
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


async def _payment_by_idempotency_key(db: AsyncSession, key: str) -> Payment | None:
    stmt = (
        select(Payment)
        .options(selectinload(Payment.attempts))
        .where(Payment.idempotency_key == key)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _validate_intent_replay(payment: Payment, *, order_id: str, provider: str) -> Payment:
    """A replayed key must reference the same request; anything else is misuse."""
    if payment.order_id != order_id or payment.provider != provider:
        raise ConflictError(
            "Idempotency-Key was already used for a different request",
            extra={"payment_id": payment.id},
        )
    return payment


def _ensure_provider_accepting_intents(
    *, provider: str, state: provider_state.ProviderState
) -> None:
    """Reject NEW intents for a disabled/maintenance provider (Task 3).

    Extracted out of :func:`create_intent` purely to keep that function's
    branch count under the ``PLR0912`` gate — it does not encapsulate any
    reusable logic beyond the single check.

    Never called from the webhook/callback settlement paths
    (``handle_webhook``, ``settle_provider_payment``,
    ``reverse_provider_payment``, ``cancel_pending_provider_payment``) — an
    already-in-flight payment must settle regardless of admin state; see
    :mod:`yupay.modules.payments.provider_state`'s module docstring.

    Raises:
        ConflictError: ``state`` is not ``"active"``. ``extra["reason"]`` is
            ``"provider_disabled"`` or ``"provider_maintenance"``.
    """
    if state != "active":
        raise ConflictError(
            "payment provider is not accepting new payments",
            provider=provider,
            reason="provider_disabled" if state == "disabled" else "provider_maintenance",
        )


def _ensure_provider_may_pay_for(*, provider: str, order: Order) -> None:
    """Refuse a gateway that must not settle this kind of order.

    `wallet.topup_limits.BLOCKED_PROVIDERS` already refuses "fund the wallet
    from the wallet" at ``/wallet/topup`` — but the charge happens in
    :func:`create_intent`, and that never consulted the purpose. A customer who
    abandoned the acquirer, which leaves the deposit ``pending_payment`` by
    design, could point a second intent at it with ``provider="wallet"``. Their
    balance nets to zero, but every lap debits ``house_payments_received`` for
    money no acquirer ever sent and books a delivered deposit, and it repeats
    for as long as they care to.

    Extracted rather than inlined to keep :func:`create_intent` under the
    ``PLR0912`` branch gate, the same reason
    :func:`_ensure_provider_accepting_intents` sits beside it.

    Raises:
        ConflictError: the wallet was asked to pay for a non-catalogue order.
    """
    if provider == "wallet" and order.purpose != "catalog":
        raise ConflictError(
            "the wallet cannot pay for a wallet top-up",
            extra={"purpose": order.purpose},
        )


def _safe_return_url(candidate: str | None, settings: Settings) -> str:
    """Resolve the acquirer return URL, defaulting to the web order surface and
    rejecting any client-supplied URL that isn't same-origin as web_base_url."""
    base = (settings.web_base_url or settings.base_url).rstrip("/")
    if not candidate:
        return f"{base}/checkout/return"
    want, got = urlparse(base), urlparse(candidate)
    if (got.scheme, got.netloc) != (want.scheme, want.netloc):
        raise ValidationError("return_url must be on the storefront origin")
    return candidate


async def create_intent(
    db: AsyncSession,
    *,
    order_id: str,
    provider: str,
    return_url: str | None,
    idempotency_key: str | None = None,
) -> Payment:
    """Create or reuse a payment intent for ``order_id`` via ``provider``.

    A repeated ``idempotency_key`` replays the original payment — including
    after the order walked past ``pending_payment`` (the timeout-retry case),
    where the status guard below would otherwise answer 409.
    """
    if idempotency_key is not None:
        replay = await _payment_by_idempotency_key(db, idempotency_key)
        if replay is not None:
            return _validate_intent_replay(replay, order_id=order_id, provider=provider)

    order = await _load_order(db, order_id, for_update=True)

    if idempotency_key is not None:
        # Re-check under the order lock: a concurrent retry that won the race
        # committed its payment while we waited on FOR UPDATE.
        replay = await _payment_by_idempotency_key(db, idempotency_key)
        if replay is not None:
            return _validate_intent_replay(replay, order_id=order_id, provider=provider)

    if order.status != "pending_payment":
        raise ConflictError("order is not awaiting payment", extra={"status": order.status})

    gw = get_gateway(provider)
    _ensure_provider_may_pay_for(provider=gw.provider, order=order)
    if not gw.available:
        raise ConflictError(
            "payment provider not available",
            extra={"provider": gw.provider},
        )

    # Admin-controlled provider state (Task 3): a disabled/maintenance provider
    # rejects NEW intents, but never touches an already-in-flight payment — the
    # webhook/callback settlement paths (handle_webhook, settle_provider_payment,
    # reverse_provider_payment, cancel_pending_provider_payment) deliberately do
    # not consult this, so a payment created while active still settles even if
    # the provider is disabled before the customer finishes paying.
    state = await provider_state.get_state(db, gw.provider)
    _ensure_provider_accepting_intents(provider=gw.provider, state=state)

    # Reuse the pending payment for this order — one intent at a time.
    existing = await _find_active_payment(db, order.id)
    if existing is not None and existing.provider == gw.provider:
        return existing
    if existing is not None and existing.provider != gw.provider:
        raise ConflictError(
            "an active payment already exists for this order with a different provider",
            extra={"current_provider": existing.provider},
        )

    safe_return_url = _safe_return_url(return_url, get_settings())

    payment_id = new_id()
    try:
        intent = await gw.create_intent(
            db=db,
            order=order,
            return_url=safe_return_url,
        )
    except (PaymentGatewayError, PaymentNotIntegratedError) as exc:
        log.warning("payments.create_intent.failed", provider=provider, error=str(exc))
        # Pass the gateway's reason through so the storefront / admin
        # can surface "insufficient wallet balance" instead of a
        # generic "rejected". Each adapter curates the message that
        # reaches the user — we never echo raw upstream JSON.
        raise ConflictError(
            f"payment provider rejected the request: {exc}",
            extra={"provider": provider},
        ) from exc

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
        idempotency_key=idempotency_key,
    )
    # SAVEPOINT: a key collision (concurrent retry, or reuse on another order)
    # must roll back only this insert, never the request transaction.
    try:
        async with db.begin_nested():
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
    except IntegrityError as exc:
        replay = (
            await _payment_by_idempotency_key(db, idempotency_key)
            if idempotency_key is not None
            else None
        )
        if replay is not None:
            return _validate_intent_replay(replay, order_id=order.id, provider=gw.provider)
        raise ConflictError("payment could not be created") from exc

    # Synchronous gateways (the wallet today; possibly direct-debit
    # crypto later) settle inside ``create_intent`` itself — there's no
    # webhook coming. Walk the order to ``paid`` + kick off fulfilment
    # in the same DB transaction so the wallet debit, the order
    # transition, and the fulfilment task creation all commit (or roll
    # back) together. This is the safety contract that keeps a wallet
    # debit from happening without a paid order, or an order from
    # flipping to ``paid`` without the debit landing.
    if payment.status == "succeeded":
        synthetic_event = WebhookEvent(
            external_event_id=f"sync:{payment.id}",
            external_payment_id=payment.external_id,
            outcome="succeeded",
            raw={"synthetic": True, "provider": gw.provider},
        )
        await _mark_payment_succeeded(db, payment=payment, event=synthetic_event)
        await db.flush()
    return payment


async def _is_held_for_review(db: AsyncSession, order_id: str) -> bool:
    """Whether a human has been asked to decide about this order.

    Read from the event log rather than a column: the hold is already recorded
    there by ``risk.hold_for_review``, and a second source of truth for "is
    this waiting on somebody" is a second thing to keep in sync.
    """
    stmt = (
        select(func.count())
        .select_from(OrderEvent)
        .where(OrderEvent.order_id == order_id, OrderEvent.kind == "order.held_for_review")
    )
    return bool((await db.execute(stmt)).scalar_one() or 0)


async def _complete_wallet_topup(db: AsyncSession, *, order: Order, payment: Payment) -> None:
    """Credit ``user_wallet`` and close the funding order. Idempotent.

    Fulfilment is skipped: there is no SKU. ``notify_order_delivered`` is
    skipped: it talks about codes. Replay after a crash between ``paid`` and
    ``delivered`` re-runs the idempotent ledger post and finishes the walk.
    """
    if order.user_id is None:
        raise ConflictError("wallet top-up has no user")
    await wallet_api.credit_topup(
        db,
        user_id=order.user_id,
        amount=payment.amount,
        currency=payment.currency,
        provider=payment.provider,
        payment_id=payment.id,
    )
    if order.status == "delivered":
        return
    moment = now()
    order.status = "delivered"
    if order.paid_at is None:
        order.paid_at = moment
    order.fulfilled_at = order.fulfilled_at or moment
    order.delivered_at = moment
    order.updated_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.wallet_credited",
            payload={
                "payment_id": payment.id,
                "amount": str(payment.amount),
                "currency": payment.currency,
            },
            actor="payments",
        )
    )
    await db.flush()
    await _publish_status_changed(order)


#: Statuses an order reaches when we gave up waiting for the money. The
#: acquirer does not know that — nothing cancels its side when we expire ours —
#: so a callback can still arrive against one of these.
_ABANDONED_STATUSES: Final[frozenset[str]] = frozenset({"expired", "cancelled"})


async def _settle_late_payment(
    db: AsyncSession, *, order: Order, payment: Payment, event: WebhookEvent
) -> None:
    """The customer was debited after we had written the order off.

    Leaving the order ``expired`` was the worst of the options: the money is
    ours, the customer has nothing, and ``list_stuck_paid_orders`` — the one
    watchdog for exactly that situation — keys on ``paid_at`` and so never
    looked. The order therefore moves to ``paid`` whatever we had decided
    earlier, and from there the two purposes diverge:

    * a **deposit on an expired order** is credited outright. Expiry is
      mechanical and blameless — the customer was slow with an SMS code —
      and there is nothing to source or re-price.
    * everything else is held: a **catalogue order**, whose price and stock
      were settled ten minutes ago and no longer bind, and a deposit on an
      order somebody **cancelled**, which is a decision a late callback must
      not quietly reverse. Cancellation is only ever an operator's doing
      (``cancel_order_admin`` is the single writer of that status), usually
      because the order looked wrong; auto-crediting would hand the balance
      to exactly that account, where it can be spent before anyone reads the
      alert — and ``reverse_topup`` then refuses the clawback.

    Either way a human releases the hold in one click, or refunds.

    ``cancelled_at`` is deliberately left where it is: it records that we did
    expire this order, which is the fact that explains the event beside it.
    """
    # Expiry is the sweep giving up on us; cancellation is a person deciding.
    # Only the first is safe to settle automatically.
    lapsed = order.status == "expired"
    moment = now()
    order.status = "paid"
    if order.paid_at is None:
        order.paid_at = moment
    order.updated_at = moment
    await affiliate_attribution.bind_attribution(db, order=order)
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.paid_after_expiry",
            payload={
                "payment_id": payment.id,
                "provider": payment.provider,
                "external_event_id": event.external_event_id,
                "expired_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
            },
            actor="payments",
        )
    )
    await db.flush()
    await _publish_status_changed(order)

    log.warning(
        "payments.paid_after_expiry",
        order_id=order.id,
        provider=payment.provider,
        purpose=order.purpose,
    )
    from yupay.modules.notifications.api import schedule_after_commit, send_admin_alert

    alert = (
        f"<b>Оплата пришла на истёкший заказ</b>\n"
        f"Заказ {order.id} ({order.purpose}), {payment.amount} {payment.currency} "
        f"через {payment.provider}."
    )
    if order.purpose == "wallet_topup" and lapsed:
        await _complete_wallet_topup(db, order=order, payment=payment)
        alert += "\nБаланс пополнен."
        schedule_after_commit(db, lambda: send_admin_alert(alert, kind="paid_after_expiry"))
        return

    # `hold_for_review` pages ops itself, with the wording for this reason, so
    # alerting here too would be the same event told twice.
    from yupay.modules.orders.risk import REASON_PAID_AFTER_EXPIRY, hold_for_review

    await hold_for_review(db, order=order, reason=REASON_PAID_AFTER_EXPIRY)


async def _mark_payment_succeeded(
    db: AsyncSession, *, payment: Payment, event: WebhookEvent
) -> None:
    """Single-spot transition: payment → succeeded and order → paid."""
    moment = now()
    payment.status = "succeeded"
    payment.succeeded_at = moment
    payment.updated_at = moment

    order = (await db.execute(select(Order).where(Order.id == payment.order_id))).scalar_one()

    if order.status in _ABANDONED_STATUSES:
        await _settle_late_payment(db, order=order, payment=payment, event=event)
        return

    if order.status == "pending_payment":
        order.status = "paid"
        order.paid_at = moment
        order.updated_at = moment
        # Binds the buyer to the partner whose code they used, if any. Never
        # raises and returns False when there is nothing to do, so the
        # affiliate program can never be the reason a settled payment fails to
        # record.
        await affiliate_attribution.bind_attribution(db, order=order)
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
        await db.flush()
        await _publish_status_changed(order)
        if order.purpose == "wallet_topup":
            await _complete_wallet_topup(db, order=order, payment=payment)
            return
        # Synchronous saga (ADR-0013). Will move to an outbox/Dramatiq actor once
        # the worker is wired up — the public service signature stays the same.
        from yupay.modules.fulfillment import service as fulfillment_svc
        from yupay.modules.orders.risk import hold_for_review, review_reason

        # The one place worth asking "should a human look first". Delivery is
        # irreversible — an issued code or a credited game balance cannot be
        # taken back — while a hold costs one click to release. The order stays
        # ``paid`` either way; only the saga is withheld (ADR-0047).
        reason = await review_reason(db, order)
        if reason is None:
            await fulfillment_svc.start_for_order(db, order_id=order.id)
        else:
            await hold_for_review(db, order=order, reason=reason)

        # No "payment received" Telegram push — the only customer-facing
        # notification is the delivery one (``notify_order_delivered``,
        # fired from the fulfilment saga when the order reaches
        # ``delivered``). A separate "оплата получена" ping was noisy and,
        # for async top-ups, wrongly promised "пришлём код". Re-enable
        # here if a "received, working on it" message is wanted later.


async def _publish_status_changed(order: Order) -> None:
    """Nudge the order's owner (if any) over the realtime channel.

    No-op for guest orders (``order.user_id is None``) — that check lives in
    ``publish_order_event`` itself. Imported lazily to avoid pulling the WS
    route stack into every payment-webhook import.
    """
    from yupay.modules.realtime import api as realtime

    await realtime.publish_order_event(
        order.user_id,
        {
            "type": "order.status_changed",
            "orderId": order.id,
            "status": order.status,
            "at": order.updated_at.isoformat(),
        },
    )


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
        # Persist the rejection so we can audit signature-mismatch attacks
        # later. The body is untrusted and pre-auth, so cap what we store —
        # otherwise a flood of oversized bodies amplifies into unbounded
        # storage even though every one of them gets rejected.
        truncated_body = body.decode("utf-8", errors="replace")[:_REJECTED_WEBHOOK_BODY_CAP]
        db.add(
            PaymentWebhook(
                id=new_id(),
                provider=gw.provider,
                external_event_id=f"rejected:{new_id()}",
                payload={"body": truncated_body},
                signature_ok=False,
            )
        )
        # Commit NOW: the raise below makes the request transaction roll
        # back, which would silently erase this audit row otherwise.
        await db.commit()
        raise ValidationError(
            "webhook signature or shape verification failed",
            extra={"provider": gw.provider, "reason": str(exc)},
        ) from exc

    # Idempotency: rely on the partial unique on (provider, external_event_id).
    # SAVEPOINT: a duplicate must roll back only this insert, never the
    # caller's request-scoped transaction.
    try:
        async with db.begin_nested():
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
            await db.flush()
    except IntegrityError:
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
        await _mark_payment_terminal(db, payment=payment, event=event, new_status="cancelled")
    # ``pending``: a signed-but-non-terminal callback (e.g. Octo's "created" /
    # "waiting_for_capture"). The webhook row above is the audit trail; we do not
    # touch the payment/order FSM and wait for the terminal callback. See ADR-0020.

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
            select(Payment).options(selectinload(Payment.attempts)).where(Payment.id == payment_id)
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

    import json

    body = json.dumps(
        {
            "event_id": f"sim_{new_id()}",
            "payment_id": payment.external_id,
            "outcome": outcome,
        }
    ).encode("utf-8")
    return await handle_webhook(db, provider=payment.provider, headers={}, body=body) or payment


async def get_active_payment(db: AsyncSession, order_id: str) -> Payment | None:
    """Public wrapper around :func:`_find_active_payment` for routes that need
    to surface the in-flight intent (mainly the owner-facing «pay now» button
    on the order detail page). Returns ``None`` when no pending intent exists
    — callers map that to 404."""
    return await _find_active_payment(db, order_id)


async def get_payment(db: AsyncSession, payment_id: str) -> Payment:
    stmt = select(Payment).options(selectinload(Payment.attempts)).where(Payment.id == payment_id)
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    return payment


async def _book_refund_ledger(
    db: AsyncSession,
    *,
    payment: Payment,
    order: Order,
    refund_amount: Decimal,
    reason: str | None,
    is_full: bool,
    actor: str,
) -> None:
    """Book the refund on the ledger. A wallet-funded payment is reversed
    straight back to the customer's balance (the exact inverse of the original
    ``wallet_payment``); every other provider books the refund as a house
    expense against provider clearing. See ADR-0023."""
    if payment.provider == "wallet":
        # Wallet payments always have a logged-in user (the gateway rejects
        # guest orders), so order.user_id is set here.
        if order.user_id is None:  # pragma: no cover -- defensive
            raise ConflictError("wallet payment has no user to refund")
        user_wallet = await wallet_api.ensure_account(
            db,
            owner_type="user",
            owner_id=order.user_id,
            kind="user_wallet",
            currency=payment.currency,
        )
        house_payments_received = await wallet_api.ensure_account(
            db,
            owner_type="house",
            owner_id="house",
            kind="house_payments_received",
            currency=payment.currency,
        )
        await wallet_api.post(
            db,
            kind="payment.refund",
            legs=[
                # D on user_wallet (NORMAL=D) → customer balance ↑ by amount.
                wallet_api.Leg(
                    account_id=user_wallet.id,
                    direction="D",
                    amount=refund_amount,
                    currency=payment.currency,
                ),
                # C on house_payments_received (NORMAL=D) → reverses the receipt.
                wallet_api.Leg(
                    account_id=house_payments_received.id,
                    direction="C",
                    amount=refund_amount,
                    currency=payment.currency,
                ),
            ],
            idempotency_key=f"refund:{payment.id}",
            reference=wallet_api.Reference(type="payment", id=payment.id),
            actor=actor,
            metadata={"reason": reason or "", "full": is_full, "credited_account": user_wallet.id},
        )
    elif order.purpose == "wallet_topup":
        if order.user_id is None:  # pragma: no cover -- deposits always have a user
            raise ConflictError("wallet top-up has no user to refund")
        try:
            await wallet_api.reverse_topup(
                db,
                user_id=order.user_id,
                amount=refund_amount,
                currency=payment.currency,
                provider=payment.provider,
                payment_id=payment.id,
                actor=actor,
            )
        except ConflictError:
            from yupay.modules.notifications.alerts import send_admin_alert

            await send_admin_alert(
                (
                    f"<b>Кошелёк: возврат пополнения заблокирован</b>\n"
                    f"payment {payment.id}: на балансе меньше чем "
                    f"{refund_amount} {payment.currency}"
                ),
                kind="wallet_topup_refund_blocked",
            )
            raise
    else:
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
            actor=actor,
            metadata={"reason": reason or "", "full": is_full},
        )


async def _apply_refund_reversal(
    db: AsyncSession,
    *,
    payment: Payment,
    amount: Decimal,
    actor: str,
    external_ref: str | None,
) -> None:
    """Shared refund core — the single place a refund touches the FSM and ledger.

    Flips the payment to ``refunded`` / ``partially_refunded``, walks the order to
    ``refunded`` (full refunds only), posts the double-entry reversal via
    :func:`_book_refund_ledger`, and cancels any still-open fulfilment. Both the
    admin refund (:func:`refund_admin`) and the provider-driven reversal
    (:func:`reverse_provider_payment`, Payme ``CancelTransaction`` on a performed
    tx) funnel through here so the ledger posting lives in exactly one place.

    Args:
        db: Active session; the caller flushes/commits.
        payment: The payment being reversed (already validated by the caller).
        amount: Refund amount; ``== payment.amount`` means a full refund.
        actor: Audit actor for the order event and ledger posting
            (``admin:<id>`` for admin refunds, the provider slug otherwise).
        external_ref: Free-text reason (admin) or provider event id (provider),
            recorded on the order event and the ledger metadata.
    """
    moment = now()
    is_full = amount == payment.amount
    payment.status = "refunded" if is_full else "partially_refunded"
    payment.updated_at = moment

    # Order: mark refunded only for a full refund. Partial refunds keep the
    # original status — they're an accounting concern, not an FSM concern.
    order = (await db.execute(select(Order).where(Order.id == payment.order_id))).scalar_one()
    refunded_now = is_full and order.status != "refunded"
    if refunded_now:
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
                "amount": str(amount),
                "full": is_full,
                "reason": external_ref or "",
            },
            actor=actor,
        )
    )

    await _book_refund_ledger(
        db,
        payment=payment,
        order=order,
        refund_amount=amount,
        reason=external_ref,
        is_full=is_full,
        actor=actor,
    )

    # A full refund walks the order to ``refunded`` — cancel any still-open
    # fulfilment task so the saga stops trying to deliver (or stops sitting in
    # a stuck ``failed`` state) for an order the customer no longer owns.
    # Already-``succeeded`` tasks are left alone: a money refund does not
    # retract a code the customer already received. Partial refunds keep the
    # order delivered, so they don't touch fulfilment. Lazy import dodges the
    # payments.service ↔ fulfillment.service ↔ api.v1 import cycle.
    if is_full:
        from yupay.modules.fulfillment import service as fulfillment_svc

        await fulfillment_svc.cancel_open_tasks_for_order(
            db, order_id=order.id, reason=f"refund:{payment.id}"
        )

    # Realtime parity: nudge a connected viewer when a full refund walks the
    # order to ``refunded`` (polling is off while the socket is up).
    if refunded_now:
        await _publish_status_changed(order)


async def settle_admin(
    db: AsyncSession,
    *,
    payment_id: str,
    admin_id: str,
    reason: str,
    provider_reference: str,
) -> Payment:
    """Mark a stuck payment as received, on an operator's word.

    For the one case the automated path can't cover: the acquirer charged the
    customer but its callback never arrived, so the order would sit in
    ``pending_payment`` until it expires. Everything else in the system treats
    "payment succeeded" as something only a provider may assert, and this is the
    single deliberate exception — so it is fenced accordingly:

    * legal only from ``pending`` / ``requires_action``; a settled, cancelled or
      refunded payment is refused rather than silently re-run;
    * ``provider_reference`` is required — the transaction id from the acquirer's
      own console. It is the evidence that a human actually verified the charge,
      and it lands in the audit trail so the claim can be re-checked later;
    * the settlement funnels through :func:`settle_provider_payment`, i.e. the
      same ``_mark_payment_succeeded`` chokepoint a real webhook uses, so the
      order transition and the fulfilment kickoff cannot diverge from the
      automated path.

    Note this *does* start fulfilment: real goods, real supplier balance.

    Raises:
        NotFoundError: unknown payment.
        ConflictError: payment is not awaiting settlement.
    """
    # FOR UPDATE so the status guard below is atomic against a real webhook
    # landing at the same moment — otherwise both could pass the check and the
    # order would be settled twice.
    payment = (
        await db.execute(select(Payment).where(Payment.id == payment_id).with_for_update())
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")
    if payment.status not in ("pending", "requires_action"):
        raise ConflictError(
            "payment is not awaiting settlement",
            extra={"status": payment.status},
        )

    db.add(
        PaymentAttempt(
            id=new_id(),
            payment_id=payment.id,
            kind="settle",
            status="ok",
            payload={
                "reason": reason,
                "provider_reference": provider_reference,
                "by": f"admin:{admin_id}",
            },
        )
    )
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=payment.order_id,
            kind="admin.payment_settled",
            payload={
                "payment_id": payment.id,
                "provider": payment.provider,
                "provider_reference": provider_reference,
                "reason": reason,
            },
            actor=f"admin:{admin_id}",
        )
    )
    # Same chokepoint a provider webhook uses — payment → succeeded, order →
    # paid, fulfilment kicked off. The external event id records that this was
    # a human decision, not a callback.
    await settle_provider_payment(
        db, payment=payment, external_event_id=f"admin-settle:{provider_reference}"
    )
    await db.flush()
    return payment


async def refund_admin(
    db: AsyncSession,
    *,
    payment_id: str,
    admin_id: str,
    amount: Decimal | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Payment:
    """Admin-initiated refund.

    Calls the gateway's ``refund`` hook (if implemented), flips the payment to
    ``refunded`` / ``partially_refunded``, walks the order to ``refunded``, and
    posts a double-entry on the ledger. The posting depends on how the order
    was paid (see ADR-0023):

    * External provider (card / Click / Payme / crypto) — money is clawed back
      through the acquirer, so the refund is booked as a house expense::

          D house_refunds                 amount
          C provider_clearing:<provider>  amount

    * Wallet — the customer paid from their in-house balance and there is no
      external leg to settle. The refund is the **exact inverse** of the
      original ``wallet_payment`` so the money lands straight back in the
      customer's wallet::

          D user_wallet:<user>            amount   (balance ↑)
          C house_payments_received       amount   (reverses the receipt)

    ``amount`` defaults to the full charged amount. The skeleton enforces a
    strict **one refund per payment**: the state guard below only admits a
    ``succeeded`` payment, and any refund — full or partial — moves the status
    off ``succeeded`` (to ``refunded`` / ``partially_refunded``), so a second
    call is rejected with a ``ConflictError``. Because at most one refund can
    ever occur, the per-payment ledger idempotency key (``refund:<payment.id>``)
    and the single-``last_refund`` replay check are sufficient and cannot
    silently no-op a distinct second refund.

    This means a partial refund currently consumes the payment's only refund —
    there is no cumulative/remaining-balance tracking. Multi/partial refunds
    (e.g. 60 then 40 of a 100 payment) need a dedicated ``payment_refunds``
    table that records each refund and derives the remaining balance; that is a
    future feature, out of scope here.
    """
    # FOR UPDATE serialises concurrent refunds of the same payment so the
    # replay check below sees the winner's committed metadata, not a stale row.
    payment = (
        await db.execute(
            select(Payment)
            .options(selectinload(Payment.attempts))
            .where(Payment.id == payment_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("payment not found")

    if idempotency_key is not None:
        last_refund = (payment.extra_metadata or {}).get("last_refund") or {}
        if last_refund.get("idempotency_key") == idempotency_key:
            # Replay: the refund already happened — no gateway call, no
            # second ledger posting, same payment back.
            return payment

    # One refund per payment: only a ``succeeded`` payment may be refunded. A
    # prior refund (full → ``refunded`` or partial → ``partially_refunded``)
    # moves the status off ``succeeded``, so this rejects any second refund.
    # This is the invariant that makes the per-payment ledger key and the
    # single ``last_refund`` replay check safe — see the docstring.
    if payment.status != "succeeded":
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
    refund_metadata: dict[str, Any] = {
        "refund_amount": str(refund_amount),
        "reason": reason or "",
        "admin_id": admin_id,
    }
    if idempotency_key is not None:
        refund_metadata["idempotency_key"] = idempotency_key

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
            # Commit NOW: the raise below makes the request transaction roll
            # back, which would silently erase this audit row otherwise.
            await db.commit()
            raise ConflictError(
                "payment provider rejected the refund",
                extra={"reason": str(exc)},
            ) from exc
    else:
        # Stubbed provider — record the intent but skip the network call.
        refund_metadata["dry_run"] = True

    is_full = refund_amount == payment.amount
    payment.extra_metadata = {**payment.extra_metadata, "last_refund": refund_metadata}

    _record_attempt(
        db,
        payment_id=payment.id,
        kind="refund",
        status="ok",
        payload=refund_metadata,
    )

    # Shared refund core (also used by the provider-driven reversal): flips the
    # payment, walks the order to ``refunded``, posts the ledger reversal, and
    # cancels open fulfilment. ``external_ref`` carries the admin's free-text
    # reason here.
    await _apply_refund_reversal(
        db,
        payment=payment,
        amount=refund_amount,
        actor=f"admin:{admin_id}",
        external_ref=reason,
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


async def settle_provider_payment(
    db: AsyncSession, *, payment: Payment, external_event_id: str
) -> None:
    """Provider-driven success (e.g. Payme ``PerformTransaction``).

    Builds a synthetic :class:`WebhookEvent` and funnels through the single
    :func:`_mark_payment_succeeded` chokepoint — payment → succeeded, order →
    paid, fulfilment saga kicked off — so a provider callback never becomes a
    second code path that flips order status. Idempotent: a no-op when the
    payment already reached ``succeeded`` (e.g. a retried callback).

    Locks the payment row (``SELECT ... FOR UPDATE``) before the status guard
    so this check-then-write is atomic against a concurrent
    ``cancel_pending_provider_payment``/``reverse_provider_payment`` on the
    SAME payment (it can be shared across sibling transactions on retried
    checkouts — see ``_ensure_payment``).

    Args:
        db: Active session; the caller commits.
        payment: The pending payment the provider just confirmed. Must be a
            persistent, session-attached row (the caller's job to load it).
        external_event_id: The provider's event/transaction id, recorded on the
            resulting ``order.paid`` event for audit.
    """
    await db.refresh(payment, with_for_update=True)
    if payment.status == "succeeded":
        order = (await db.execute(select(Order).where(Order.id == payment.order_id))).scalar_one()
        # Finish a walk that crashed between ``paid`` and ``delivered``. A
        # deposit waiting on an operator looks identical by status, so ask
        # whether anyone was told to decide about it first — otherwise one
        # retried callback releases a hold nobody released.
        if (
            order.purpose == "wallet_topup"
            and order.status != "delivered"
            and not await _is_held_for_review(db, order.id)
        ):
            await _complete_wallet_topup(db, order=order, payment=payment)
        return
    event = WebhookEvent(
        external_event_id=external_event_id,
        external_payment_id=payment.external_id,
        outcome="succeeded",
        raw={},
    )
    await _mark_payment_succeeded(db, payment=payment, event=event)
    await db.flush()


async def reverse_provider_payment(
    db: AsyncSession, *, payment: Payment, external_event_id: str, actor: str = "payme"
) -> None:
    """Provider-driven refund of a SUCCEEDED payment (e.g. Payme
    ``CancelTransaction`` on a performed tx, state 2 → -2).

    Runs the SAME ledger reversal + order → ``refunded`` as an admin refund via
    the shared :func:`_apply_refund_reversal` core (always a full reversal for a
    provider cancel). Idempotent: a no-op when the payment is already
    ``refunded``.

    Locks the payment row (``SELECT ... FOR UPDATE``) before the status guard
    so this check-then-write is atomic against a concurrent
    ``settle_provider_payment``/``cancel_pending_provider_payment`` on the
    SAME payment (it can be shared across sibling transactions on retried
    checkouts — see ``_ensure_payment``).

    Args:
        db: Active session; the caller commits.
        payment: The succeeded payment the provider is reversing. Must be a
            persistent, session-attached row (the caller's job to load it).
        external_event_id: The provider's cancel event id, recorded for audit.
        actor: Audit actor for the order event and ledger posting.
    """
    await db.refresh(payment, with_for_update=True)
    if payment.status == "refunded":
        return
    await _apply_refund_reversal(
        db,
        payment=payment,
        amount=payment.amount,
        actor=actor,
        external_ref=external_event_id,
    )
    await db.flush()


async def cancel_pending_provider_payment(
    db: AsyncSession, *, payment: Payment, actor: str = "payme"
) -> None:
    """Provider-driven cancel of a PENDING payment (e.g. Payme
    ``CancelTransaction`` on an unperformed tx, state 1 → -1).

    Marks the payment ``cancelled`` through the single :func:`_mark_payment_terminal`
    chokepoint — no ledger, no fulfilment, the order stays ``pending_payment``.
    Cancels IFF still pending (under a row lock); a no-op on any already-
    terminal/succeeded status.

    Locks the payment row (``SELECT ... FOR UPDATE``) before the status guard
    so this check-then-write is atomic against a concurrent
    ``settle_provider_payment``/``reverse_provider_payment`` on the SAME
    payment — it can be shared across sibling transactions on retried
    checkouts (see ``_ensure_payment``), so a sibling settling the payment and
    a stale-timeout sweep cancelling it can otherwise both read ``pending``
    before either commits. Guarding on ``!= "pending"`` (rather than
    ``== "cancelled"``) means a payment a sibling already settled to
    ``succeeded`` is NEVER clawed back to ``cancelled`` with no ledger
    reversal.

    Args:
        db: Active session; the caller commits.
        payment: The pending payment the provider is cancelling. Must be a
            persistent, session-attached row (the caller's job to load it).
        actor: Audit actor threaded onto the synthetic event's ``raw``.
    """
    await db.refresh(payment, with_for_update=True)
    if payment.status != "pending":
        return
    event = WebhookEvent(
        external_event_id=f"provider-cancel:{payment.id}",
        external_payment_id=payment.external_id,
        outcome="cancelled",
        raw={"actor": actor},
    )
    await _mark_payment_terminal(db, payment=payment, event=event, new_status="cancelled")
    await db.flush()


async def list_webhooks_admin(
    db: AsyncSession,
    *,
    provider: str | None = None,
    signature_ok: bool | None = None,
    limit: int = 50,
) -> list[PaymentWebhook]:
    """Admin listing of received webhooks for the audit / debugging page."""
    stmt = select(PaymentWebhook).order_by(PaymentWebhook.received_at.desc()).limit(limit)
    if provider is not None:
        stmt = stmt.where(PaymentWebhook.provider == provider)
    if signature_ok is not None:
        stmt = stmt.where(PaymentWebhook.signature_ok.is_(signature_ok))
    return list((await db.execute(stmt)).scalars().all())


async def mark_webhook_resolved(
    db: AsyncSession,
    *,
    webhook_id: str,
    actor_email: str,
    reason: str,
) -> PaymentWebhook:
    """Admin stamp of "I looked at this, it's not stuck — drop from feed".

    Production webhook records do not store the raw HTTP body or signature
    headers, so a true retry would require re-asking the provider. The
    realistic operational action is therefore to acknowledge a rejected or
    unfinished record so it stops surfacing as "broken" in the hospital
    view. We embed an audit stub in ``payload._admin_resolved``; if the
    webhook never finished processing, we also set ``processed_at`` so it
    is no longer counted as pending.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("reason is required")

    webhook = (
        await db.execute(select(PaymentWebhook).where(PaymentWebhook.id == webhook_id))
    ).scalar_one_or_none()
    if webhook is None:
        raise NotFoundError("webhook not found")

    payload = dict(webhook.payload or {})
    payload["_admin_resolved"] = {
        "actor": actor_email,
        "reason": reason,
        "at": now().isoformat(),
    }
    webhook.payload = payload
    if webhook.processed_at is None:
        webhook.processed_at = now()
    await db.flush()
    log.info(
        "payments.webhook.resolved",
        webhook_id=webhook.id,
        provider=webhook.provider,
        actor=actor_email,
    )
    return webhook


async def list_payments_admin(
    db: AsyncSession,
    *,
    order_id: str | None = None,
    provider: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Payment, str]], int]:
    """Paged admin listing. Returns ``([(payment, order_purpose)], total)``.

    The purpose rides along because a deposit and a sale are the same shape
    here — a payment against an order id — and an operator scanning the list
    has no other way to tell them apart.
    """
    base = (
        select(Payment, Order.purpose)
        .join(Order, Order.id == Payment.order_id)
        .options(selectinload(Payment.attempts))
    )
    count_stmt = select(func.count()).select_from(Payment)
    if order_id is not None:
        base = base.where(Payment.order_id == order_id)
        count_stmt = count_stmt.where(Payment.order_id == order_id)
    if provider is not None:
        base = base.where(Payment.provider == provider)
        count_stmt = count_stmt.where(Payment.provider == provider)
    if status_filter is not None:
        base = base.where(Payment.status == status_filter)
        count_stmt = count_stmt.where(Payment.status == status_filter)
    result = await db.execute(base.order_by(Payment.created_at.desc()).limit(limit).offset(offset))
    rows = [(payment, purpose) for payment, purpose in result.all()]
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


__all__ = [
    "cancel_pending_provider_payment",
    "create_intent",
    "get_active_payment",
    "get_payment",
    "handle_webhook",
    "list_payments_admin",
    "list_webhooks_admin",
    "mark_webhook_resolved",
    "refund_admin",
    "reverse_provider_payment",
    "settle_provider_payment",
    "simulate_webhook",
]


# Defensive: silence unused-import linters; ``Decimal``/``datetime`` are referenced via
# type hints in serialised payloads but never accessed at runtime here.
_ = Decimal, datetime
