"""Payme (Paycom) Merchant API service handlers.

This module is the heart of the Payme integration: it implements the seven
JSON-RPC methods Payme's sandbox exercises — ``CheckPerformTransaction``,
``CreateTransaction``, ``PerformTransaction``, ``CancelTransaction``,
``CheckTransaction``, ``GetStatement`` and ``SetFiscalData`` — plus the
checkout-URL builder the storefront uses to launch a payment.

Every money-moving side effect funnels through the ``payments`` module's single
provider-lifecycle hooks (:func:`settle_provider_payment`,
:func:`reverse_provider_payment`, :func:`cancel_pending_provider_payment`) so a
Payme callback never becomes a second code path that flips order status or posts
the ledger. :class:`PaymeTransaction` is the source of truth for Payme's own
state machine (``1`` created, ``2`` performed, ``-1`` cancelled-before-perform,
``-2`` cancelled-after-perform) and is keyed on ``payme_id`` so every method is
idempotent against replays.
"""

from __future__ import annotations

import base64
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order
from yupay.modules.orders.risk import evidence_geo, precharge_veto, record_precharge_veto
from yupay.modules.payme.errors import (
    cannot_cancel_delivered,
    fiscal_receipt_not_found,
    invalid_amount,
    operation_not_permitted,
    order_has_pending_transaction,
    order_not_found,
    order_not_payable,
    transaction_not_found,
)
from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.payments import service as pay_svc
from yupay.modules.payments.models import Payment

# Payme's own transaction-state encoding.
_STATE_CREATED = 1
_STATE_PERFORMED = 2
_STATE_CANCELLED_PENDING = -1
_STATE_CANCELLED_PERFORMED = -2

# Order statuses that mean EVERY item is done — a state-2 cancel on such an
# order is refused with -31007. This is a coarse guard; the fine-grained one
# (:func:`_any_goods_delivered`) also refuses a still-``fulfilling`` order once
# any single item has shipped.
_DELIVERED_STATUSES = frozenset({"fulfilled", "delivered"})


def now_ms() -> int:
    """Return the current time as Payme-style epoch milliseconds."""
    return int(now().timestamp() * 1000)


def _expected_tiyin(order: Order) -> int:
    """Return the order's charge in tiyin (minor units), asserting exactness.

    ``total_charged`` is a major-unit UZS ``Decimal``; UZS has no minor unit in
    practice but the column keeps 6 dp, so ``* 100`` must land on an integer.
    A non-integral result means corrupt order data, which we surface as
    ``invalid_amount`` rather than silently truncating money.

    Args:
        order: The order whose expected Payme amount to compute.

    Returns:
        The exact amount Payme must send, in tiyin.

    Raises:
        PaymeError: ``-31001`` if ``total_charged * 100`` is not integral.
    """
    raw = order.total_charged * Decimal(100)
    if raw != raw.to_integral_value():
        raise invalid_amount()
    return int(raw)


async def _resolve_order(
    db: AsyncSession, account: dict[str, Any], *, for_update: bool = False
) -> Order:
    """Load the order named by ``account.order_id`` or raise ``-31050``.

    Args:
        db: Active session.
        account: Payme's ``account`` object; must carry ``order_id``.
        for_update: When ``True``, lock the order row (``FOR UPDATE``) so
            concurrent ``CreateTransaction`` calls on the same order serialise.

    Returns:
        The matching :class:`Order`.

    Raises:
        PaymeError: ``-31050`` if ``order_id`` is missing or unknown.
    """
    order_id = account.get("order_id")
    if not order_id:
        raise order_not_found()
    stmt = select(Order).where(Order.id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise order_not_found()
    return order


def _check_perform(order: Order, amount: int) -> None:
    """Run the shared check-perform validations against a loaded order.

    Raises:
        PaymeError: ``-31051`` if the order is not payable; ``-31001`` if the
            amount does not match the order's price.
    """
    if order.status != "pending_payment":
        raise order_not_payable()
    # Payme settles only in UZS. Reject a non-UZS order here — otherwise its
    # ``total_charged`` (in e.g. RUB) would be matched against a soum amount of
    # the same number, letting a RUB order be paid for a fraction in soums.
    if order.currency != "UZS":
        raise order_not_payable()
    if amount != _expected_tiyin(order):
        raise invalid_amount()


async def _refuse_if_vetoed(db: AsyncSession, order: Order) -> None:
    """Raise Payme's own ``-31051`` if ``order`` is pre-charge geo-vetoed.

    ADR-0063 enforcement point A, called right after :func:`_check_perform`
    passes at both its call sites. Reuses ``order_not_payable`` verbatim
    rather than a distinct code on purpose — a refusal that said "geo
    blocked" would teach a carder exactly what to spoof next, so this must
    be indistinguishable from any other not-payable order.

    Args:
        db: Active session.
        order: The already-validated (payable) order to check.

    Raises:
        PaymeError: ``-31051`` if ``precharge_veto`` returns a reason.
    """
    veto = await precharge_veto(db, order)
    if veto is None:
        return
    country, timezone = await evidence_geo(db, order.id)
    await record_precharge_veto(db, order, veto, country=country, timezone=timezone)
    raise order_not_payable()


async def _load_transaction(
    db: AsyncSession, payme_id: str, *, for_update: bool = False
) -> PaymeTransaction | None:
    """Load a Payme transaction by its ``payme_id`` (optionally locked)."""
    stmt = select(PaymeTransaction).where(PaymeTransaction.payme_id == payme_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_payment(db: AsyncSession, payment_id: str) -> Payment:
    """Load the payment backing a transaction (must exist)."""
    return (await db.execute(select(Payment).where(Payment.id == payment_id))).scalar_one()


async def _ensure_payment(db: AsyncSession, order: Order) -> Payment:
    """Reuse the order's pending Payme payment, or create a fresh one.

    Args:
        db: Active session.
        order: The order the payment belongs to.

    Returns:
        A pending ``payme`` :class:`Payment` for the order.
    """
    existing = (
        await db.execute(
            select(Payment).where(
                Payment.order_id == order.id,
                Payment.provider == "payme",
                Payment.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider="payme",
        status="pending",
        amount=order.total_charged,
        currency="UZS",
        external_id=f"payme:{order.id}",
    )
    db.add(payment)
    await db.flush()
    return payment


async def _any_goods_delivered(db: AsyncSession, order_id: str) -> bool:
    """Return ``True`` if ANY item on the order has already been delivered.

    A ``FulfillmentTask`` reaches ``succeeded`` atomically with the creation of
    its ``Delivery`` on every delivery path (supplier auto, inventory issue,
    manual completion), so a single succeeded task is proof the customer already
    holds at least one code. A multi-item order can rest at ``fulfilling`` (some
    tasks still open) while others are already delivered — the coarse
    order-status guard misses that, but this catches it. Used to refuse a
    state-2 auto-refund that would otherwise claw back money for goods already
    handed over.

    Args:
        db: Active session.
        order_id: The order to inspect.

    Returns:
        ``True`` if at least one fulfilment task for the order is ``succeeded``.
    """
    row = (
        await db.execute(
            select(FulfillmentTask.id)
            .where(
                FulfillmentTask.order_id == order_id,
                FulfillmentTask.status == "succeeded",
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def check_perform_transaction(
    db: AsyncSession, *, amount: int, account: dict[str, Any]
) -> dict[str, Any]:
    """Handle ``CheckPerformTransaction``: is this order payable for this amount?

    Args:
        db: Active session.
        amount: The amount Payme intends to charge, in tiyin.
        account: Payme's ``account`` object carrying ``order_id``.

    Returns:
        ``{"allow": True}`` when the order is payable and the amount matches.

    Raises:
        PaymeError: ``-31050`` unknown order, ``-31051`` not payable (also
            the pre-charge geo veto, ADR-0063 — deliberately the same
            code), ``-31001`` wrong amount.
    """
    order = await _resolve_order(db, account)
    _check_perform(order, amount)
    # Deliberately indistinguishable from the ``-31051`` above: a refusal
    # that says "geo blocked" teaches a carder exactly what to spoof next.
    await _refuse_if_vetoed(db, order)
    return {"allow": True}


async def create_transaction(
    db: AsyncSession, *, payme_id: str, time: int, amount: int, account: dict[str, Any]
) -> dict[str, Any]:
    """Handle ``CreateTransaction``: register a Payme transaction (state 1).

    Idempotent against replays: a second call with the same ``payme_id`` returns
    the stored result without creating a duplicate row. A second *different*
    active transaction on the same order is refused with ``-31099`` (an
    account-range error Payme mandates for a busy order).

    Args:
        db: Active session.
        payme_id: Payme's own transaction id (unique).
        time: Payme's creation timestamp (epoch ms), echoed back verbatim.
        amount: The charge amount in tiyin.
        account: Payme's ``account`` object carrying ``order_id``.

    Returns:
        ``{"create_time", "transaction", "state"}``.

    Raises:
        PaymeError: ``-31050``/``-31051``/``-31001`` from validation
            (``-31051`` also covers the pre-charge geo veto, ADR-0063 —
            deliberately the same code), ``-31099`` if the order already has
            a different active transaction.
    """
    existing = await _load_transaction(db, payme_id, for_update=True)
    if existing is not None:
        # Replay: re-validate the amount is consistent, then echo the stored
        # result. We deliberately do NOT re-check order status — a legitimate
        # replay may arrive after the order has already moved to ``paid``.
        if amount != existing.amount_tiyin:
            raise invalid_amount()
        return {
            "create_time": existing.create_time,
            "transaction": existing.id,
            "state": existing.state,
        }

    order = await _resolve_order(db, account, for_update=True)
    _check_perform(order, amount)
    # Deliberately indistinguishable from the ``-31051`` above: a refusal
    # that says "geo blocked" teaches a carder exactly what to spoof next.
    await _refuse_if_vetoed(db, order)

    other_active = (
        await db.execute(
            select(PaymeTransaction).where(
                PaymeTransaction.order_id == order.id,
                PaymeTransaction.state.in_((_STATE_CREATED, _STATE_PERFORMED)),
                PaymeTransaction.payme_id != payme_id,
            )
        )
    ).scalar_one_or_none()
    if other_active is not None:
        raise order_has_pending_transaction()

    payment = await _ensure_payment(db, order)
    txn = PaymeTransaction(
        id=new_id(),
        payme_id=payme_id,
        order_id=order.id,
        payment_id=payment.id,
        amount_tiyin=amount,
        state=_STATE_CREATED,
        create_time=time,
    )
    db.add(txn)
    await db.flush()
    return {"create_time": time, "transaction": txn.id, "state": _STATE_CREATED}


async def perform_transaction(db: AsyncSession, *, payme_id: str) -> dict[str, Any]:
    """Handle ``PerformTransaction``: confirm payment (state 1 → 2).

    Settles the backing payment through the single
    :func:`payments.service.settle_provider_payment` chokepoint — payment →
    succeeded, order → paid, fulfilment started. Idempotent: a replay on an
    already-performed transaction echoes the stored result.

    Args:
        db: Active session.
        payme_id: Payme's transaction id.

    Returns:
        ``{"transaction", "perform_time", "state"}``.

    Raises:
        PaymeError: ``-31003`` unknown transaction, ``-31008`` if the
            transaction is cancelled (state < 0).
    """
    txn = await _load_transaction(db, payme_id, for_update=True)
    if txn is None:
        raise transaction_not_found()
    if txn.state == _STATE_PERFORMED:
        return {
            "transaction": txn.id,
            "perform_time": txn.perform_time,
            "state": txn.state,
        }
    if txn.state < 0:
        raise operation_not_permitted()

    txn.state = _STATE_PERFORMED
    txn.perform_time = now_ms()
    payment = await _load_payment(db, txn.payment_id)  # type: ignore[arg-type]
    await pay_svc.settle_provider_payment(db, payment=payment, external_event_id=payme_id)
    await db.flush()
    return {
        "transaction": txn.id,
        "perform_time": txn.perform_time,
        "state": _STATE_PERFORMED,
    }


async def cancel_transaction(db: AsyncSession, *, payme_id: str, reason: int) -> dict[str, Any]:
    """Handle ``CancelTransaction``, routing strictly by current state.

    Money-safety hinges on the state routing:

    * **state 1** (created, not performed) → ``-1``; the pending payment is
      cancelled, no ledger, no refund.
    * **state 2** (performed) → ``-2``; the succeeded payment is *reversed*
      (ledger refund). If the order's goods are already delivered, the cancel is
      refused with ``-31007`` — a refund must never silently claw back money for
      a code the customer already holds.

    Idempotent: a replay on an already-cancelled transaction echoes the stored
    result.

    Args:
        db: Active session.
        payme_id: Payme's transaction id.
        reason: Payme's cancellation reason code, stored on the row.

    Returns:
        ``{"transaction", "cancel_time", "state"}``.

    Raises:
        PaymeError: ``-31003`` unknown transaction, ``-31007`` if the order is
            already delivered.
    """
    txn = await _load_transaction(db, payme_id, for_update=True)
    if txn is None:
        raise transaction_not_found()
    if txn.state in (_STATE_CANCELLED_PENDING, _STATE_CANCELLED_PERFORMED):
        return {
            "transaction": txn.id,
            "cancel_time": txn.cancel_time,
            "state": txn.state,
        }

    payment = await _load_payment(db, txn.payment_id)  # type: ignore[arg-type]

    if txn.state == _STATE_CREATED:
        txn.state = _STATE_CANCELLED_PENDING
        txn.cancel_time = now_ms()
        txn.reason = reason
        await pay_svc.cancel_pending_provider_payment(db, payment=payment, actor="payme")
    else:  # _STATE_PERFORMED
        order = (await db.execute(select(Order).where(Order.id == txn.order_id))).scalar_one()
        # Refuse the auto-refund once ANY goods have shipped — not only when the
        # WHOLE order reached fulfilled/delivered. A multi-item order can rest at
        # ``fulfilling`` with one item already delivered; a full reverse here
        # would refund money for a code the customer keeps. Such a case must be
        # settled manually (Payme cabinet + admin), never auto-full-refunded.
        if order.status in _DELIVERED_STATUSES or await _any_goods_delivered(db, txn.order_id):
            raise cannot_cancel_delivered()
        txn.state = _STATE_CANCELLED_PERFORMED
        txn.cancel_time = now_ms()
        txn.reason = reason
        await pay_svc.reverse_provider_payment(
            db, payment=payment, external_event_id=payme_id, actor="payme"
        )

    await db.flush()
    return {"transaction": txn.id, "cancel_time": txn.cancel_time, "state": txn.state}


async def check_transaction(db: AsyncSession, *, payme_id: str) -> dict[str, Any]:
    """Handle ``CheckTransaction``: report a transaction's full state.

    Args:
        db: Active session.
        payme_id: Payme's transaction id.

    Returns:
        ``{"create_time", "perform_time", "cancel_time", "transaction",
        "state", "reason"}`` — times are ``0`` when unset, ``reason`` is
        ``None`` when the transaction was never cancelled.

    Raises:
        PaymeError: ``-31003`` if no such transaction exists.
    """
    txn = await _load_transaction(db, payme_id)
    if txn is None:
        raise transaction_not_found()
    return {
        "create_time": txn.create_time,
        "perform_time": txn.perform_time,
        "cancel_time": txn.cancel_time,
        "transaction": txn.id,
        "state": txn.state,
        "reason": txn.reason,
    }


async def get_statement(db: AsyncSession, *, from_ms: int, to_ms: int) -> dict[str, Any]:
    """Handle ``GetStatement``: list transactions created in a time window.

    Args:
        db: Active session.
        from_ms: Window start (inclusive), epoch ms.
        to_ms: Window end (inclusive), epoch ms.

    Returns:
        ``{"transactions": [...]}`` ordered by ``create_time`` ascending, each
        entry shaped as Payme's statement row.
    """
    rows = (
        (
            await db.execute(
                select(PaymeTransaction)
                .where(
                    PaymeTransaction.create_time >= from_ms,
                    PaymeTransaction.create_time <= to_ms,
                )
                .order_by(PaymeTransaction.create_time.asc())
            )
        )
        .scalars()
        .all()
    )
    transactions: list[dict[str, Any]] = [
        {
            "id": row.payme_id,
            "time": row.create_time,
            "amount": row.amount_tiyin,
            "account": {"order_id": row.order_id},
            "create_time": row.create_time,
            "perform_time": row.perform_time,
            "cancel_time": row.cancel_time,
            "transaction": row.id,
            "state": row.state,
            "reason": row.reason,
            "receivers": [],
        }
        for row in rows
    ]
    return {"transactions": transactions}


async def set_fiscal_data(
    db: AsyncSession, *, payme_id: str, type_: str, fiscal_data: dict[str, Any]
) -> dict[str, Any]:
    """Handle ``SetFiscalData``: store a fiscal receipt keyed by its type.

    Args:
        db: Active session.
        payme_id: Payme's transaction id.
        type_: The fiscal-data type (e.g. ``"PERFORM"``/``"CANCEL"``).
        fiscal_data: The receipt payload to store under ``type_``.

    Returns:
        ``{"success": True}``.

    Raises:
        PaymeError: ``-32001`` if no such transaction exists.
    """
    txn = await _load_transaction(db, payme_id, for_update=True)
    if txn is None:
        raise fiscal_receipt_not_found()
    # Reassign (not mutate) so SQLAlchemy flags the JSONB column dirty.
    txn.fiscal_data = {**txn.fiscal_data, type_: fiscal_data}
    await db.flush()
    return {"success": True}


def build_checkout_url(
    *, order_id: str, amount_tiyin: int, return_url: str | None, lang: str = "ru"
) -> str:
    """Build the Payme checkout URL that launches a hosted payment.

    Payme's GET-checkout takes a base64-encoded, ``;``-delimited parameter
    string carrying the merchant id, the ``account`` fields, the amount (tiyin),
    an optional return URL and the UI language.

    Args:
        order_id: The order the payment is for (Payme ``ac.order_id``).
        amount_tiyin: The charge amount in tiyin.
        return_url: Where Payme returns the customer afterwards, or ``None``.
        lang: Checkout UI language (``"ru"``/``"uz"``/``"en"``).

    Returns:
        The absolute checkout URL: ``<checkout_url>/<base64-params>``.
    """
    settings = get_settings()
    parts = f"m={settings.payme_merchant_id};ac.order_id={order_id};a={amount_tiyin}"
    if return_url:
        parts += f";c={return_url}"
    parts += f";l={lang}"
    b64 = base64.b64encode(parts.encode()).decode()
    return f"{settings.payme_checkout_url}/{b64}"


__all__ = [
    "build_checkout_url",
    "cancel_transaction",
    "check_perform_transaction",
    "check_transaction",
    "create_transaction",
    "get_statement",
    "now_ms",
    "perform_transaction",
    "set_fiscal_data",
]
