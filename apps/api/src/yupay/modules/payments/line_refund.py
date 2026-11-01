"""Refund one undeliverable line of an order to the buyer's YuPay balance.

A pack cart puts several lines on one payment. When one of them cannot be
delivered (a one-time pack the player already bought) and the rest were, the
whole-payment refunds are wrong: «Возврат на баланс» would also pay back goods
the buyer received. This books the line's share of the payment onto the
balance, stops its task, and lets the order close as delivered on the lines
that were.

The payment ends ``partially_refunded``, which every whole-payment refund
refuses (they require ``succeeded``), and :func:`service.refunded_to_wallet`
treats a line refund as money already returned, so an acquirer's later cancel
is refused too. Nothing can pay the same line out twice.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.payments.service import _record_attempt
from yupay.modules.wallet import api as wallet_api

log = get_logger("yupay.payments.line_refund")

#: Whole so'm for UZS, two decimals elsewhere — the same granularity the order
#: total was charged at. A share is rounded down: never pay back more than the line.
_QUANTUM: Final[dict[str, Decimal]] = {"UZS": Decimal("1")}
_DEFAULT_QUANTUM: Final[Decimal] = Decimal("0.01")

#: ``payment.extra_metadata`` key holding ``{order_item_id: {amount, ...}}``.
LINE_REFUNDS_KEY: Final[str] = "line_refunds"


def _line_net(item: OrderItem) -> Decimal:
    return item.unit_price_usd * item.qty - (item.discount_usd or Decimal(0))


def line_share(items: list[OrderItem], item: OrderItem, paid: Decimal, currency: str) -> Decimal:
    """The part of ``paid`` that bought ``item``, in proportion to the lines' USD prices.

    Args:
        items: Every line of the order.
        item: The line being refunded.
        paid: The payment amount, in ``currency``.
        currency: The payment currency.

    Returns:
        The share, rounded down to the currency's chargeable unit.

    Raises:
        ConflictError: The order's lines sum to nothing.
    """
    total = sum((_line_net(i) for i in items), Decimal(0))
    if total <= 0:
        raise ConflictError("the order's lines have no price to split", reason="no_line_price")
    quantum = _QUANTUM.get(currency, _DEFAULT_QUANTUM)
    return (paid * _line_net(item) / total).quantize(quantum, rounding=ROUND_DOWN)


async def _book(
    db: AsyncSession, *, payment: Payment, order: Order, item_id: str, amount: Decimal, actor: str
) -> None:
    """Credit the balance: a wallet payment is reversed, any other leaves provider clearing."""
    assert order.user_id is not None  # checked by the caller
    user_wallet = await wallet_api.ensure_account(
        db, owner_type="user", owner_id=order.user_id, kind="user_wallet", currency=payment.currency
    )
    if payment.provider == "wallet":
        source = await wallet_api.ensure_account(
            db,
            owner_type="house",
            owner_id="house",
            kind="house_payments_received",
            currency=payment.currency,
        )
        kind = "payment.refund"
    else:
        source = await wallet_api.ensure_account(
            db,
            owner_type="provider",
            owner_id=payment.provider,
            kind="provider_clearing",
            currency=payment.currency,
        )
        kind = "payment.refund_to_wallet"
    await wallet_api.post(
        db,
        kind=kind,
        legs=[
            wallet_api.Leg(
                account_id=user_wallet.id, direction="D", amount=amount, currency=payment.currency
            ),
            wallet_api.Leg(
                account_id=source.id, direction="C", amount=amount, currency=payment.currency
            ),
        ],
        idempotency_key=f"refund_line:{item_id}",
        reference=wallet_api.Reference(type="payment", id=payment.id),
        actor=actor,
        metadata={"order_item_id": item_id, "credited_account": user_wallet.id},
    )


async def refund_line_to_wallet(
    db: AsyncSession,
    *,
    order_item_id: str,
    admin_id: str,
    idempotency_key: str,
) -> Payment:
    """Pay one failed line back to the buyer's balance and close the order if it can.

    The admin order page's «Вернуть позицию на баланс». Idempotent per line: a
    second call for a line already paid back returns the payment unchanged.

    Args:
        db: Session; the caller commits.
        order_item_id: The undeliverable line.
        admin_id: Who refunded it, for the audit trail.
        idempotency_key: The request's key, recorded on the attempt.

    Returns:
        The order's payment, now ``partially_refunded``.

    Raises:
        NotFoundError: No such line.
        ConflictError: A guest, merchant or balance top-up order; an order that
            is no longer open; a line still running or delivered; nothing else
            delivered; not exactly one paid payment; or a payment already
            refunded some other way.
    """
    from yupay.modules.fulfillment import service as fulfillment_svc

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == order_item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("order item not found")
    order = (await db.execute(select(Order).where(Order.id == item.order_id))).scalar_one()
    if order.user_id is None:
        raise ConflictError("a guest order has no balance to refund to", reason="guest_order")
    if order.merchant_id is not None:
        raise ConflictError("a merchant order is settled on its deposit", reason="merchant_order")
    if order.purpose == "wallet_topup":
        raise ConflictError("a balance top-up has no lines to refund", reason="topup")
    if order.status not in ("paid", "fulfilling"):
        # The refund that closed the order, replayed: answer it, don't refuse it.
        refunded = (
            (await db.execute(select(Payment).where(Payment.order_id == order.id))).scalars().all()
        )
        for p in refunded:
            if item.id in ((p.extra_metadata or {}).get(LINE_REFUNDS_KEY) or {}):
                return p
        raise ConflictError(
            "the order is no longer open", reason="order_closed", extra={"status": order.status}
        )

    # Lock order: fulfilment tasks first, then the payment, then the order row.
    await fulfillment_svc.release_line_for_refund(db, order_item_id=item.id)

    payments = (
        (
            await db.execute(
                select(Payment)
                .where(
                    Payment.order_id == order.id,
                    Payment.status.in_(("succeeded", "partially_refunded")),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(payments) != 1:
        raise ConflictError("the order needs exactly one paid payment", reason="payment_count")
    payment = payments[0]
    meta: dict[str, Any] = dict(payment.extra_metadata or {})
    done: dict[str, Any] = dict(meta.get(LINE_REFUNDS_KEY) or {})
    if item.id in done:
        return payment
    if payment.status != "succeeded" and not done:
        raise ConflictError("the payment was already refunded", reason="already_refunded")

    items = list(
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    )
    amount = line_share(items, item, payment.amount, payment.currency)
    already = sum((Decimal(v["amount"]) for v in done.values()), Decimal(0))
    if amount <= 0 or already + amount > payment.amount:
        raise ConflictError("nothing left to refund for this line", reason="amount")

    actor = f"admin:{admin_id}"
    await _book(db, payment=payment, order=order, item_id=item.id, amount=amount, actor=actor)
    entry = {"amount": str(amount), "admin_id": admin_id, "at": now().isoformat()}
    payment.extra_metadata = {**meta, LINE_REFUNDS_KEY: {**done, item.id: entry}}
    payment.status = "partially_refunded"
    item.fulfillment_state = "refunded"  # «Возврат» on the line, not «Ошибка»
    payment.updated_at = now()
    _record_attempt(
        db,
        payment_id=payment.id,
        kind="refund",
        status="ok",
        payload={
            "order_item_id": item.id,
            "refund_amount": str(amount),
            "refunded_to": "wallet",
            "admin_id": admin_id,
            "idempotency_key": idempotency_key,
        },
    )
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind=fulfillment_svc.LINE_REFUNDED_EVENT,
            payload={
                "order_item_id": item.id,
                "payment_id": payment.id,
                "amount": str(amount),
                "currency": payment.currency,
            },
            actor=actor,
        )
    )
    await db.flush()
    await fulfillment_svc.settle_order_if_done(db, order_id=order.id)
    await db.flush()
    log.info(
        "payments.line_refund.ok",
        order_id=order.id,
        order_item_id=item.id,
        amount=str(amount),
        currency=payment.currency,
    )
    return payment
