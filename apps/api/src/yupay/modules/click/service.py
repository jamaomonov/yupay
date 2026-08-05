"""Click Shop API service handlers.

This module is the heart of the Click integration: it implements the two
HTTPS webhooks Click drives as the customer pays — ``/prepare`` and
``/complete`` — plus the checkout-URL builder the storefront and mini app use
to launch a payment. It is the inverted-webhook twin of
:mod:`yupay.modules.uzum.service`, mirroring its structure with Click's own
verbs, statuses and error codes.

Every money-moving side effect funnels through the ``payments`` module's
single provider-lifecycle hooks (:func:`settle_provider_payment`,
:func:`cancel_pending_provider_payment`) so a Click callback never becomes a
second code path that flips order status or posts the ledger.
:class:`ClickTransaction` is the source of truth for Click's own state
machine (``PREPARED`` / ``CONFIRMED`` / ``CANCELLED``) and is keyed on
``(click_trans_id, service_id)`` so ``/prepare`` is idempotent against
replays, while ``/complete`` is keyed on the ``merchant_prepare_id`` we
handed back at Prepare time (see ``docs/superpowers/specs/
2026-07-23-click-shop-api-design.md`` §7).

Click's MD5 ``sign_string`` verification happens in the ROUTE layer (Task 5),
where the raw form-encoded values are available — every function here
receives already-verified fields and only ever raises :class:`ClickError` for
business/state failures. ``sign_time`` is still accepted on ``prepare``/
``complete`` for wire-contract parity with Click's request shape, but it is
not used for any decision here (freshness/replay is the signature layer's
concern), so it is discarded immediately.
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
from yupay.modules.click.errors import (
    already_paid,
    incorrect_amount,
    sign_check_failed,
    transaction_cancelled,
    transaction_not_found,
    user_not_found,
)
from yupay.modules.click.models import ClickTransaction
from yupay.modules.orders.models import Order
from yupay.modules.payments import service as pay_svc
from yupay.modules.payments.models import Payment


async def _resolve_order(
    db: AsyncSession, order_id: str | None, *, for_update: bool = False
) -> Order:
    """Load the order named by ``merchant_trans_id`` or raise ``-5``.

    Args:
        db: Active session.
        order_id: The order id from Click's ``merchant_trans_id``, or ``None``.
        for_update: When ``True``, lock the order row (``FOR UPDATE``) so
            concurrent ``/prepare`` calls on the same order serialise.

    Returns:
        The matching :class:`Order`.

    Raises:
        ClickError: ``-5`` if ``order_id`` is missing or unknown.
    """
    if not order_id:
        raise user_not_found()
    stmt = select(Order).where(Order.id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise user_not_found()
    return order


def _check_order_state(order: Order) -> None:
    """Assert the order is payable, raising Click's dedicated codes otherwise.

    Args:
        order: The order to check.

    Raises:
        ClickError: ``-4`` if the order is already paid; ``-9`` for any other
            non-``pending_payment`` status (cancelled, expired, refunded, or
            any further-along fulfilment status).
    """
    if order.status == "paid":
        raise already_paid()
    if order.status != "pending_payment":
        raise transaction_cancelled()
    # Click settles only in UZS. A non-UZS order's ``total_charged`` (e.g. RUB)
    # must not be payable here — otherwise it could be settled with a soum
    # amount of the same number, for a fraction of the real value.
    if order.currency != "UZS":
        raise transaction_cancelled()


def _provider_for_service(service_id: int) -> str:
    """Map an inbound Click ``service_id`` to our provider id.

    Click routes the same Prepare/Complete contract through two services that
    share one merchant — the web storefront (``click_service_id_web``) and
    the Telegram mini app (``click_service_id_bot``). The provider id picked
    here becomes the backing ``payments`` row's ``provider`` column.

    Args:
        service_id: The ``service_id`` field from an inbound Click request.

    Returns:
        ``"click"`` for the web service, ``"click_miniapp"`` for the bot
        service.

    Raises:
        ClickError: ``-1`` if ``service_id`` matches neither configured
            service. In practice the route layer already rejects an unknown
            ``service_id`` while verifying the signature (no secret is
            configured for it), so this is a defensive fallback, not the
            primary guard.
    """
    settings = get_settings()
    if settings.click_service_id_web is not None and service_id == settings.click_service_id_web:
        return "click"
    if settings.click_service_id_bot is not None and service_id == settings.click_service_id_bot:
        return "click_miniapp"
    raise sign_check_failed()


async def _load_txn_by_click(
    db: AsyncSession, *, click_trans_id: int, service_id: int, for_update: bool = False
) -> ClickTransaction | None:
    """Load a Click transaction by its ``(click_trans_id, service_id)`` pair."""
    stmt = select(ClickTransaction).where(
        ClickTransaction.click_trans_id == click_trans_id,
        ClickTransaction.service_id == service_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_txn_by_prepare_id(
    db: AsyncSession, merchant_prepare_id: int, *, for_update: bool = False
) -> ClickTransaction | None:
    """Load a Click transaction by the ``merchant_prepare_id`` we issued."""
    stmt = select(ClickTransaction).where(
        ClickTransaction.merchant_prepare_id == merchant_prepare_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_payment(db: AsyncSession, payment_id: str) -> Payment:
    """Load the payment backing a transaction (must exist)."""
    return (await db.execute(select(Payment).where(Payment.id == payment_id))).scalar_one()


async def _ensure_payment(db: AsyncSession, order: Order, *, provider: str) -> Payment:
    """Reuse the order's pending payment for this provider, or create a fresh one.

    Args:
        db: Active session.
        order: The order the payment belongs to.
        provider: ``"click"`` or ``"click_miniapp"`` (see
            :func:`_provider_for_service`) — a customer retrying checkout on
            the SAME surface reuses one pending payment; a retry on the
            OTHER surface gets its own.

    Returns:
        A pending :class:`Payment` for the order under ``provider``.
    """
    existing = (
        await db.execute(
            select(Payment).where(
                Payment.order_id == order.id,
                Payment.provider == provider,
                Payment.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider=provider,
        status="pending",
        amount=order.total_charged,
        currency="UZS",
        external_id=f"{provider}:{order.id}",
    )
    db.add(payment)
    await db.flush()
    return payment


def _prepare_response(txn: ClickTransaction) -> dict[str, Any]:
    """Build the ``/prepare`` success body from a (new or replayed) row."""
    return {
        "click_trans_id": txn.click_trans_id,
        "merchant_trans_id": txn.order_id,
        "merchant_prepare_id": txn.merchant_prepare_id,
        "error": 0,
        "error_note": "Success",
    }


async def prepare(
    db: AsyncSession,
    *,
    click_trans_id: int,
    service_id: int,
    click_paydoc_id: int | None,
    merchant_trans_id: str,
    amount: str,
    sign_time: str,
) -> dict[str, Any]:
    """Handle ``/prepare``: validate the order and allocate a transaction row.

    Idempotent on ``(click_trans_id, service_id)`` — a replay (Click retrying
    the same Prepare call) returns the same ``merchant_prepare_id`` rather
    than erroring or inserting a second row.

    Args:
        db: Active session.
        click_trans_id: Click's own transaction id.
        service_id: Which Click service sent this request (108149 web /
            108150 bot) — picks the backing payment's provider.
        click_paydoc_id: Click's ``click_paydoc_id``, stored for audit.
        merchant_trans_id: Our order id.
        amount: The ``amount`` field, as received (raw wire string, soums) —
            compared to ``order.total_charged`` via ``Decimal``.
        sign_time: Accepted for wire-contract parity; unused (see module
            docstring).

    Returns:
        ``{"click_trans_id", "merchant_trans_id", "merchant_prepare_id",
        "error": 0, "error_note": "Success"}``.

    Raises:
        ClickError: ``-5`` unknown order, ``-4`` already paid, ``-9``
            cancelled/expired/refunded, ``-2`` amount mismatch.
    """
    del sign_time  # signature parity only; see module docstring.

    existing = await _load_txn_by_click(
        db, click_trans_id=click_trans_id, service_id=service_id, for_update=True
    )
    if existing is not None:
        return _prepare_response(existing)

    order = await _resolve_order(db, merchant_trans_id, for_update=True)
    _check_order_state(order)
    if Decimal(str(amount)) != order.total_charged:
        raise incorrect_amount()

    provider = _provider_for_service(service_id)
    payment = await _ensure_payment(db, order, provider=provider)

    txn = ClickTransaction(
        id=new_id(),
        click_trans_id=click_trans_id,
        service_id=service_id,
        order_id=order.id,
        payment_id=payment.id,
        amount=Decimal(str(amount)),
        status="PREPARED",
        click_paydoc_id=click_paydoc_id,
        prepare_time=now(),
    )
    # SAVEPOINT: the pre-check above is not a lock (a FOR UPDATE against a
    # not-yet-existing row locks nothing), so two concurrent first-time
    # ``/prepare`` calls for the same (click_trans_id, service_id) can both
    # pass it and both reach this insert. The loser's flush raises
    # IntegrityError on the unique pair; catch it here so only this insert
    # rolls back (not the whole request), then re-read the winner's row and
    # return ITS merchant_prepare_id — Click's replay contract requires the
    # same idempotent success, not an error (mirrors the Uzum §12 savepoint
    # fix, adapted since Click's replay is a 200/success, not a dedicated
    # error code).
    try:
        async with db.begin_nested():
            db.add(txn)
            await db.flush()
    except IntegrityError:
        winner = await _load_txn_by_click(db, click_trans_id=click_trans_id, service_id=service_id)
        if winner is None:  # pragma: no cover - defensive; the row must exist post-collision
            raise
        return _prepare_response(winner)

    return _prepare_response(txn)


async def complete(
    db: AsyncSession,
    *,
    click_trans_id: int,
    service_id: int,
    merchant_trans_id: str,
    merchant_prepare_id: int,
    amount: str,
    sign_time: str,
) -> dict[str, Any]:
    """Handle ``/complete``: Click debited the customer; settle the payment.

    Settles the backing payment through the single
    :func:`payments.service.settle_provider_payment` chokepoint — payment →
    succeeded, order → paid, fulfilment started.

    Args:
        db: Active session.
        click_trans_id: Click's own transaction id — cross-checked against
            the row loaded by ``merchant_prepare_id``.
        service_id: Cross-checked against the row loaded by
            ``merchant_prepare_id``.
        merchant_trans_id: Our order id — cross-checked against the row's
            ``order_id``.
        merchant_prepare_id: The id we handed back at Prepare time; the
            lookup key for this call.
        amount: The ``amount`` field, as received (raw wire string, soums) —
            compared to the amount recorded at Prepare via ``Decimal``.
        sign_time: Accepted for wire-contract parity; unused (see module
            docstring).

    Returns:
        ``{"click_trans_id", "merchant_trans_id", "merchant_confirm_id",
        "error": 0, "error_note": "Success"}``.

    Raises:
        ClickError: ``-6`` unknown/mismatched ``merchant_prepare_id``, ``-4``
            already confirmed (replay), ``-9`` cancelled, ``-2`` amount
            mismatch.
    """
    del sign_time  # signature parity only; see module docstring.

    txn = await _load_txn_by_prepare_id(db, merchant_prepare_id, for_update=True)
    if (
        txn is None
        or txn.click_trans_id != click_trans_id
        or txn.service_id != service_id
        or txn.order_id != merchant_trans_id
    ):
        raise transaction_not_found()
    if txn.status == "CONFIRMED":
        raise already_paid()
    if txn.status == "CANCELLED":
        raise transaction_cancelled()
    if Decimal(str(amount)) != txn.amount:
        raise incorrect_amount()

    payment = await _load_payment(db, txn.payment_id)  # type: ignore[arg-type]
    await pay_svc.settle_provider_payment(
        db, payment=payment, external_event_id=str(click_trans_id)
    )

    txn.status = "CONFIRMED"
    txn.complete_time = now()
    await db.flush()

    return {
        "click_trans_id": txn.click_trans_id,
        "merchant_trans_id": txn.order_id,
        "merchant_confirm_id": txn.merchant_prepare_id,
        "error": 0,
        "error_note": "Success",
    }


async def cancel(
    db: AsyncSession,
    *,
    merchant_prepare_id: int | None = None,
    click_trans_id: int | None = None,
    service_id: int | None = None,
) -> None:
    """Cancel a Click transaction: the negative-inbound-``error`` path + the
    stale-prepare sweep (Task 7) both funnel through this.

    Look up the transaction either by ``merchant_prepare_id`` (available on
    ``/complete``, and on the sweep) or by ``(click_trans_id, service_id)``
    (the only identifiers Click sends on ``/prepare``, where no
    ``merchant_prepare_id`` exists yet from Click's point of view). A no-op
    when there is nothing to cancel — no such transaction, or it is already
    ``CANCELLED``.

    Money-safety (the Uzum-final-review lesson, carried forward exactly):
    :func:`_ensure_payment` can share one pending payment across several
    transactions on the same order (a customer retrying checkout). If a
    sibling transaction already confirmed that payment (→ succeeded, order →
    paid) while THIS one is still ``PREPARED``, cancelling here must NOT claw
    back that now-succeeded payment out from under the paid order — only
    this transaction moves to ``CANCELLED``. A transaction that is itself
    already ``CONFIRMED`` is left entirely alone (both its own status and its
    payment) — Click v1 has no merchant-initiated refund, so an already-
    settled transaction is never touched here.

    Args:
        db: Active session.
        merchant_prepare_id: The id to look up by, if known.
        click_trans_id: Together with ``service_id``, the pair to look up by
            when ``merchant_prepare_id`` is not yet known (the ``/prepare``
            negative-error path).
        service_id: See ``click_trans_id``.

    Raises:
        ValueError: Neither lookup key was supplied.
    """
    if merchant_prepare_id is not None:
        txn = await _load_txn_by_prepare_id(db, merchant_prepare_id, for_update=True)
    elif click_trans_id is not None and service_id is not None:
        txn = await _load_txn_by_click(
            db, click_trans_id=click_trans_id, service_id=service_id, for_update=True
        )
    else:
        raise ValueError("cancel() requires merchant_prepare_id or (click_trans_id, service_id)")

    if txn is None or txn.status != "PREPARED":
        return

    payment = await _load_payment(db, txn.payment_id)  # type: ignore[arg-type]
    if payment.status == "pending":
        await pay_svc.cancel_pending_provider_payment(db, payment=payment, actor="click")

    txn.status = "CANCELLED"
    txn.cancel_time = now()
    await db.flush()


def build_checkout_url(*, provider: str, order_id: str, amount: Decimal, return_url: str) -> str:
    """Build the ``my.click.uz`` checkout URL that launches a payment.

    Args:
        provider: ``"click"`` (web) or ``"click_miniapp"`` (Telegram mini
            app) — picks the service id Click routes the payment through.
        order_id: The order the payment is for; echoed back by Click as
            ``merchant_trans_id`` on both webhooks.
        amount: The charge amount in soums (major units), e.g.
            ``order.total_charged``.
        return_url: Where Click returns the customer afterwards.

    Returns:
        The absolute checkout URL, e.g. ``https://my.click.uz/services/pay
        ?service_id=<id>&merchant_id=<id>&amount=<amount>
        &transaction_param=<order_id>&return_url=<url>``.

    Raises:
        ValueError: ``provider`` is neither ``"click"`` nor
            ``"click_miniapp"``.
    """
    settings = get_settings()
    if provider == "click":
        service_id = settings.click_service_id_web
    elif provider == "click_miniapp":
        service_id = settings.click_service_id_bot
    else:
        raise ValueError(f"unknown click provider: {provider!r}")

    query: dict[str, Any] = {
        "service_id": service_id,
        "merchant_id": settings.click_merchant_id,
        "amount": amount,
        "transaction_param": order_id,
        "return_url": return_url,
    }
    return f"{settings.click_pay_url}?{urlencode(query)}"


__all__ = [
    "build_checkout_url",
    "cancel",
    "complete",
    "prepare",
]
