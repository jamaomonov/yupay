"""Uzum Bank Merchant API service handlers.

This module is the heart of the Uzum integration: it implements the five
HTTPS webhooks Uzum drives as the customer pays — ``/check``, ``/create``,
``/confirm``, ``/reverse`` and ``/status`` — plus the checkout-URL builder the
storefront uses to launch a payment. It is the inverted-webhook twin of
:mod:`yupay.modules.payme.service`, mirroring its structure with Uzum's own
verbs, statuses and error codes.

Every money-moving side effect funnels through the ``payments`` module's
single provider-lifecycle hooks (:func:`settle_provider_payment`,
:func:`reverse_provider_payment`, :func:`cancel_pending_provider_payment`) so
a Uzum callback never becomes a second code path that flips order status or
posts the ledger. :class:`UzumTransaction` is the source of truth for Uzum's
own state machine (``CREATED`` / ``CONFIRMED`` / ``REVERSED`` / ``FAILED``)
and is keyed on ``trans_id`` so every method is idempotent against replays —
unlike Payme, Uzum signals a replay with a dedicated error code rather than an
echoed result (see ``docs/superpowers/specs/
2026-07-22-uzum-merchant-api-design.md`` §12).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order
from yupay.modules.orders.risk import precharge_veto_full, record_precharge_veto
from yupay.modules.payments import service as pay_svc
from yupay.modules.payments.models import Payment
from yupay.modules.uzum.errors import (
    invalid_amount,
    order_not_found,
    payment_already_made,
    payment_cancelled,
    transaction_already_cancelled,
    transaction_already_confirmed,
    transaction_already_created,
    transaction_cancelled,
    transaction_cannot_be_cancelled,
    transaction_not_found,
)
from yupay.modules.uzum.models import UzumTransaction

# Order statuses that mean EVERY item is done — a reverse of a CONFIRMED
# transaction on such an order is refused with 10017. This is a coarse guard;
# the fine-grained one (:func:`_any_goods_delivered`) also refuses a still-
# ``fulfilling`` order once any single item has shipped.
_DELIVERED_STATUSES = frozenset({"fulfilled", "delivered"})


def now_ms() -> int:
    """Return the current time as Uzum-style epoch milliseconds."""
    return int(now().timestamp() * 1000)


def _expected_tiyin(order: Order) -> int:
    """Return the order's charge in tiyin (minor units), asserting exactness.

    ``total_charged`` is a major-unit UZS ``Decimal``; UZS has no minor unit in
    practice but the column keeps 6 dp, so ``* 100`` must land on an integer.
    A non-integral result means corrupt order data, which we surface as
    ``invalid_amount`` rather than silently truncating money.

    Args:
        order: The order whose expected Uzum amount to compute.

    Returns:
        The exact amount Uzum must send, in tiyin.

    Raises:
        UzumError: ``10011`` if ``total_charged * 100`` is not integral.
    """
    raw = order.total_charged * Decimal(100)
    if raw != raw.to_integral_value():
        raise invalid_amount()
    return int(raw)


def _amount_value(order: Order) -> str:
    """Return the order's charge as a plain major-unit UZS (sum) string.

    Uzum's app prefills the payment amount from ``/check``'s
    ``data.amount.value`` when the buyer opens checkout, and expects it in
    **sums** (major units), not tiyin. ``total_charged`` is already a
    major-unit UZS ``Decimal``; UZS has no sub-sum denomination in practice, so
    a whole-sum charge renders as a bare integer string (``"130000"``). A
    charge that carries fractional sums (allowed as long as ``* 100`` is
    integral — see :func:`_expected_tiyin`) keeps its decimal places rather
    than being silently rounded.

    Args:
        order: The order whose charge to render for Uzum's app.

    Returns:
        The charge in sums as a string, e.g. ``"130000"``.
    """
    amount = order.total_charged
    if amount == amount.to_integral_value():
        return str(int(amount))
    # The column keeps 6 dp, so a fractional charge reads back with trailing
    # zeros (130000.50 -> 130000.500000); strip them. ``normalize`` is safe
    # here because only genuinely-fractional values reach this branch — a
    # whole-sum charge (which ``normalize`` would render in exponent form,
    # e.g. 1.3E+5) is handled by the integer branch above.
    return format(amount.normalize(), "f")


async def _resolve_order(
    db: AsyncSession, order_id: str | None, *, for_update: bool = False
) -> Order:
    """Load the order named by ``params.order_id`` or raise ``10007``.

    Args:
        db: Active session.
        order_id: The order id from Uzum's ``params.order_id``, or ``None``.
        for_update: When ``True``, lock the order row (``FOR UPDATE``) so
            concurrent ``/create`` calls on the same order serialise.

    Returns:
        The matching :class:`Order`.

    Raises:
        UzumError: ``10007`` if ``order_id`` is missing or unknown.
    """
    if not order_id:
        raise order_not_found()
    stmt = select(Order).where(Order.id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise order_not_found()
    return order


def _check_order_state(order: Order) -> None:
    """Assert the order is payable, raising Uzum's dedicated codes otherwise.

    Args:
        order: The order to check.

    Raises:
        UzumError: ``10008`` if the order is already paid; ``10009`` for any
            other non-``pending_payment`` status (cancelled, expired,
            refunded, or any further-along fulfilment status).
    """
    if order.status == "paid":
        raise payment_already_made()
    if order.status != "pending_payment":
        raise payment_cancelled()
    # Uzum settles only in UZS. Reject a non-UZS order — otherwise its
    # ``total_charged`` (e.g. RUB) would match a soum amount of the same
    # number, letting it be paid for a fraction of the real value.
    if order.currency != "UZS":
        raise payment_cancelled()


async def _load_tx(
    db: AsyncSession, trans_id: str, *, for_update: bool = False
) -> UzumTransaction | None:
    """Load a Uzum transaction by its ``trans_id`` (optionally locked)."""
    stmt = select(UzumTransaction).where(UzumTransaction.trans_id == trans_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_payment(db: AsyncSession, payment_id: str) -> Payment:
    """Load the payment backing a transaction (must exist)."""
    return (await db.execute(select(Payment).where(Payment.id == payment_id))).scalar_one()


async def _ensure_payment(db: AsyncSession, order: Order) -> Payment:
    """Reuse the order's pending Uzum payment, or create a fresh one.

    Args:
        db: Active session.
        order: The order the payment belongs to.

    Returns:
        A pending ``uzum`` :class:`Payment` for the order.
    """
    existing = (
        await db.execute(
            select(Payment).where(
                Payment.order_id == order.id,
                Payment.provider == "uzum",
                Payment.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider="uzum",
        status="pending",
        amount=order.total_charged,
        currency="UZS",
        external_id=f"uzum:{order.id}",
    )
    db.add(payment)
    await db.flush()
    return payment


async def _any_goods_delivered(db: AsyncSession, order_id: str) -> bool:
    """Return ``True`` if ANY item on the order has already been delivered.

    A ``FulfillmentTask`` reaches ``succeeded`` atomically with the creation of
    its ``Delivery`` on every delivery path (supplier auto, inventory issue,
    manual completion), so a single succeeded task is proof the customer
    already holds at least one code. A multi-item order can rest at
    ``fulfilling`` (some tasks still open) while others are already delivered
    — the coarse order-status guard misses that, but this catches it. Used to
    refuse a ``/reverse`` that would otherwise claw back money for goods
    already handed over.

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


async def check(db: AsyncSession, *, service_id: int, params: dict[str, Any]) -> dict[str, Any]:
    """Handle ``/check``: may this order be paid for these params?

    ``service_id`` is accepted (and would be echoed by the route layer, which
    also validates it against ``10006``) purely for signature parity with the
    other four handlers; ``/check`` itself carries no amount to validate.

    Args:
        db: Active session.
        service_id: Uzum's ``serviceId``, unused here (see above).
        params: Uzum's ``params`` object carrying ``order_id``.

    Returns:
        ``{"status": "OK", "data": {"amount": {"value": <sums>}}}`` when the
        order is payable — ``data.amount.value`` carries the charge in sums so
        Uzum's app prefills the amount when the buyer opens checkout.

    Raises:
        UzumError: ``10007`` unknown order, ``10008`` already paid, ``10009``
            cancelled/expired/refunded/otherwise not payable (also the
            pre-charge geo veto, ADR-0063 — deliberately the same code).
    """
    del service_id  # signature parity only; see docstring.
    order = await _resolve_order(db, params.get("order_id"))
    _check_order_state(order)
    # ADR-0063 enforcement point A: refuse with the same generic 10009
    # ``_check_order_state`` already uses for a non-payable order —
    # indistinguishable on purpose, since a refusal that said "geo blocked"
    # would teach a carder exactly what to spoof next.
    veto = await precharge_veto_full(db, order)
    if veto.reason is not None:
        await record_precharge_veto(
            db, order, veto.reason, country=veto.country, timezone=veto.timezone
        )
        raise payment_cancelled()
    return {"status": "OK", "data": {"amount": {"value": _amount_value(order)}}}


async def create(
    db: AsyncSession,
    *,
    service_id: int,
    trans_id: str,
    params: dict[str, Any],
    amount: int,
) -> dict[str, Any]:
    """Handle ``/create``: register a pending Uzum transaction (``CREATED``).

    Unlike Payme, a replay is refused outright with a dedicated code
    (``10010``) rather than echoed — Uzum's own idempotency signal.

    Args:
        db: Active session.
        service_id: Uzum's ``serviceId``, stored on the row for audit.
        trans_id: Uzum's own transaction id (unique) — the idempotency key.
        params: Uzum's ``params`` object carrying ``order_id``.
        amount: The charge amount in tiyin.

    Returns:
        ``{"transId", "status": "CREATED", "transTime", "amount"}``. ``data``
        is only returned by ``/check`` and ``/status`` (optional elsewhere).

    Raises:
        UzumError: ``10010`` if ``trans_id`` was already created (either the
            pre-check finds it, or a concurrent ``/create`` wins the race and
            the insert collides on the unique ``trans_id``); ``10007``/
            ``10008``/``10009`` from the order-state check; ``10011`` if
            ``amount`` does not match the order's price.
    """
    existing = await _load_tx(db, trans_id, for_update=True)
    if existing is not None:
        raise transaction_already_created()

    order = await _resolve_order(db, params.get("order_id"), for_update=True)
    _check_order_state(order)
    if amount != _expected_tiyin(order):
        raise invalid_amount()

    payment = await _ensure_payment(db, order)
    create_time = now_ms()
    txn = UzumTransaction(
        id=new_id(),
        trans_id=trans_id,
        order_id=order.id,
        payment_id=payment.id,
        amount_tiyin=amount,
        status="CREATED",
        service_id=service_id,
        create_time=create_time,
    )
    # SAVEPOINT: the pre-check above is not a lock (a FOR UPDATE against a
    # not-yet-existing row locks nothing), so two concurrent first-time
    # ``/create`` calls for the same trans_id can both pass it and both reach
    # this insert. The loser's flush raises IntegrityError on the unique
    # trans_id; catch it here so only this insert rolls back (not the whole
    # request), and report it the way Uzum's spec mandates for a duplicate
    # trans_id (10010) instead of letting it surface as an uncaught 99999.
    try:
        async with db.begin_nested():
            db.add(txn)
            await db.flush()
    except IntegrityError:
        raise transaction_already_created() from None
    return {
        "transId": trans_id,
        "status": "CREATED",
        "transTime": create_time,
        "amount": amount,
    }


async def confirm(
    db: AsyncSession, *, trans_id: str, payment_source: dict[str, Any]
) -> dict[str, Any]:
    """Handle ``/confirm``: Uzum debited the customer; deliver the goods.

    Settles the backing payment through the single
    :func:`payments.service.settle_provider_payment` chokepoint — payment →
    succeeded, order → paid, fulfilment started.

    Args:
        db: Active session.
        trans_id: Uzum's transaction id.
        payment_source: The ``paymentSource``/``tariff``/``phone``/``cardType``
            block Uzum sends, stored verbatim for audit.

    Returns:
        ``{"transId", "status": "CONFIRMED", "confirmTime", "amount"}``.
        ``data`` is only returned by ``/check`` and ``/status``.

    Raises:
        UzumError: ``10014`` unknown transaction, ``10016`` if already
            confirmed, ``10015`` if reversed/failed (cannot confirm further).
    """
    txn = await _load_tx(db, trans_id, for_update=True)
    if txn is None:
        raise transaction_not_found()
    if txn.status == "CONFIRMED":
        raise transaction_already_confirmed()
    if txn.status in {"REVERSED", "FAILED"}:
        raise transaction_cancelled()

    payment = await _load_payment(db, txn.payment_id)  # type: ignore[arg-type]
    txn.payment_source = payment_source
    confirm_time = now_ms()
    txn.status = "CONFIRMED"
    txn.confirm_time = confirm_time
    await pay_svc.settle_provider_payment(db, payment=payment, external_event_id=trans_id)
    await db.flush()
    return {
        "transId": trans_id,
        "status": "CONFIRMED",
        "confirmTime": confirm_time,
        "amount": txn.amount_tiyin,
    }


async def reverse(db: AsyncSession, *, trans_id: str) -> dict[str, Any]:
    """Handle ``/reverse``: cancel a pending transaction or refund a confirmed one.

    Money-safety hinges on the state routing:

    * **CREATED** (and **FAILED**, e.g. from the 30-min timeout sweep) → the
      backing payment is cancelled, no ledger, no refund — but ONLY while that
      payment is still ``pending``. ``_ensure_payment`` reuses one order's
      pending ``uzum`` payment across every ``/create`` call for that order,
      so a sibling transaction may have already confirmed it (payment ->
      ``succeeded``, order -> paid) while this one sits CREATED. Cancelling a
      ``succeeded`` payment here would corrupt a paid (possibly delivered)
      order and brick ``refund_admin``, so a payment that is no longer
      pending is left untouched — only the transaction itself moves to
      REVERSED.
    * **CONFIRMED** → the succeeded payment is *reversed* (ledger refund). If
      the order's goods are already delivered, the reverse is refused with
      ``10017`` — a refund must never silently claw back money for a code the
      customer already holds.

    Args:
        db: Active session.
        trans_id: Uzum's transaction id.

    Returns:
        ``{"transId", "status": "REVERSED", "reverseTime", "amount"}``.
        ``data`` is only returned by ``/check`` and ``/status``.

    Raises:
        UzumError: ``10014`` unknown transaction, ``10018`` if already
            reversed, ``10017`` if a CONFIRMED transaction's order is already
            delivered.
    """
    txn = await _load_tx(db, trans_id, for_update=True)
    if txn is None:
        raise transaction_not_found()
    if txn.status == "REVERSED":
        raise transaction_already_cancelled()

    payment = await _load_payment(db, txn.payment_id)  # type: ignore[arg-type]

    if txn.status == "CONFIRMED":
        order = (await db.execute(select(Order).where(Order.id == txn.order_id))).scalar_one()
        # Refuse the auto-refund once ANY goods have shipped — not only when
        # the WHOLE order reached fulfilled/delivered. A multi-item order can
        # rest at ``fulfilling`` with one item already delivered; a full
        # reverse here would refund money for a code the customer keeps. Such
        # a case must be settled manually, never auto-full-refunded.
        if order.status in _DELIVERED_STATUSES or await _any_goods_delivered(db, txn.order_id):
            raise transaction_cannot_be_cancelled()
        await pay_svc.reverse_provider_payment(
            db, payment=payment, external_event_id=trans_id, actor="uzum"
        )
    elif payment.status == "pending":
        # CREATED, or FAILED (the 30-min timeout sweep already marks the
        # backing payment cancelled — this is an idempotent no-op then): no
        # successful charge was ever settled on THIS transaction, so there is
        # nothing to reverse on the ledger, only the pending payment to
        # cancel. Guarded on the PAYMENT's own status (not just the
        # transaction's) because the backing payment may be SHARED with a
        # sibling transaction on the same order (see ``_ensure_payment``)
        # that has since been confirmed — a payment a sibling already settled
        # is left untouched here (that sibling owns its terminal state); the
        # transaction below still moves to REVERSED either way.
        await pay_svc.cancel_pending_provider_payment(db, payment=payment, actor="uzum")

    reverse_time = now_ms()
    txn.status = "REVERSED"
    txn.reverse_time = reverse_time
    await db.flush()
    return {
        "transId": trans_id,
        "status": "REVERSED",
        "reverseTime": reverse_time,
        "amount": txn.amount_tiyin,
    }


async def status(db: AsyncSession, *, trans_id: str) -> dict[str, Any]:
    """Handle ``/status``: report a transaction's current state.

    This is Uzum's reconciliation channel — it retries this up to 10× after a
    failed/timed-out ``/confirm`` until we report a terminal state.

    Args:
        db: Active session.
        trans_id: Uzum's transaction id.

    Returns:
        ``{"transId", "status", "transTime", "confirmTime", "reverseTime",
        "data", "amount"}`` — ``confirmTime``/``reverseTime`` are ``None``
        when unset.

    Raises:
        UzumError: ``10014`` if no such transaction exists.
    """
    txn = await _load_tx(db, trans_id)
    if txn is None:
        raise transaction_not_found()
    return {
        "transId": trans_id,
        "status": txn.status,
        "transTime": txn.create_time,
        "confirmTime": txn.confirm_time,
        "reverseTime": txn.reverse_time,
        "data": {},
        "amount": txn.amount_tiyin,
    }


def build_checkout_url(*, order_id: str, amount_tiyin: int, return_url: str | None) -> str:
    """Build the Uzum open-service checkout URL that launches a payment.

    Args:
        order_id: The order the payment is for (Uzum ``params.order_id``).
        amount_tiyin: The charge amount in tiyin.
        return_url: Where Uzum returns the customer afterwards, or ``None``
            to omit ``redirectUrl`` entirely.

    Returns:
        The absolute checkout URL, e.g. ``https://www.uzumbank.uz/open-service
        ?serviceId=<id>&order_id=<order_id>&amount=<tiyin>&redirectUrl=<url>``.
    """
    settings = get_settings()
    query: dict[str, Any] = {
        "serviceId": settings.uzum_service_id,
        "order_id": order_id,
        "amount": amount_tiyin,
    }
    if return_url:
        query["redirectUrl"] = return_url
    return f"{settings.uzum_open_service_url}?{urlencode(query)}"


__all__ = [
    "build_checkout_url",
    "check",
    "confirm",
    "create",
    "now_ms",
    "reverse",
    "status",
]
