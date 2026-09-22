"""Paynet UWS method handlers.

We are Paynet's JSON-RPC **server**: their terminal network calls us over the
life of a payment, and their protocol state is authoritative until the
transaction settles. Every money effect still goes through the same
``payments.service`` hooks every other gateway uses
(:func:`settle_provider_payment`, :func:`reverse_provider_payment`), so a
Paynet callback never becomes a second code path that flips an order status or
posts to the ledger.

The shape differs from Payme in three ways worth holding in mind:

* **There is no CreateTransaction.** ``PerformTransaction`` opens and settles
  in one call, so a row exists only once money has moved. Idempotency rests
  entirely on Paynet's ``transactionId``.
* **Times are strings, not epochs** — ``YYYY-MM-dd HH:mm:ss`` at GMT+5, with
  one documented exception on the way in (see :func:`check_transaction`).
* **An unknown transaction is not an error** in ``CheckTransaction``: the spec
  wants a successful envelope carrying ``transactionState: 3``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order
from yupay.modules.payments import service as pay_svc
from yupay.modules.payments.models import Payment
from yupay.modules.paynet.errors import (
    cancel_refused_delivered,
    invalid_amount,
    invalid_datetime,
    order_already_paid,
    order_not_found,
    order_not_payable,
    transaction_already_exists,
    transaction_not_found,
    unknown_service,
)
from yupay.modules.paynet.models import (
    STATE_CANCELLED,
    STATE_NOT_FOUND,
    STATE_SUCCESS,
    UQ_EXTERNAL_TRANSACTION,
    PaynetTransaction,
)

log = get_logger("yupay.paynet.uws")

PROVIDER: Final = "paynet"
#: The account field a payer's link carries. Contractual — it is what we filled
#: into Table 3 of «Порядок технического взаимодействия», so renaming it is a
#: change to the signed annex, not a refactor.
ACCOUNT_FIELD: Final = "order_id"
#: The spec fixes GMT+5 for every timestamp. A fixed offset rather than
#: ``ZoneInfo("Asia/Tashkent")`` on purpose: the contract says +5, and a
#: tzdata update that ever gave Uzbekistan a DST rule must not silently move
#: our reconciliation timestamps away from what Paynet expects.
TASHKENT: Final = timezone(timedelta(hours=5))
_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
_PAYABLE: Final = "pending_payment"
_PAID_STATUSES: Final = frozenset({"paid", "fulfilling", "fulfilled", "delivered", "refunded"})
_DELIVERED_STATUSES: Final = frozenset({"fulfilled", "delivered"})


def stamp(moment: datetime) -> str:
    """Render a moment as Paynet's ``YYYY-MM-dd HH:mm:ss`` at GMT+5."""
    return moment.astimezone(TASHKENT).strftime(_TIME_FORMAT)


def parse_stamp(value: str) -> datetime:
    """Parse Paynet's standard timestamp, assuming GMT+5 when it says nothing.

    Raises:
        ValueError: the string is not in the documented format.
    """
    return datetime.strptime(value, _TIME_FORMAT).replace(tzinfo=TASHKENT)


async def get_information(
    db: AsyncSession, *, service_id: int, fields: dict[str, Any]
) -> dict[str, Any]:
    """Handle ``GetInformation``: is this order payable, and for how much.

    Args:
        db: Active session.
        service_id: Paynet's service identifier; must be the one we registered.
        fields: The account object, carrying ``order_id``.

    Returns:
        ``{"status": "0", "timestamp", "fields"}`` — ``fields`` echoes the
        order and the exact amount owed, in soʻm (not tiyin — see
        :func:`_expected_som`), as a string.

    Raises:
        PaynetError: unknown service, unknown order, an order that is not
            awaiting payment, or (``302``) one already paid — see
            :func:`_load_payable_order`'s ``paid_is_not_found``: a settled
            bill has nothing left to show a payer, so this method answers the
            same as "no such order" rather than ``PerformTransaction``'s 201.
    """
    _assert_service(service_id)
    order = await _load_payable_order(db, _account(fields), paid_is_not_found=True)
    return {
        # String, not int (2026-09-22, Дильшод/Paynet certification): every
        # other field in this envelope that carries a business value is
        # already a string for the same reason ``amount`` below is — a JSON
        # number has been through a float somewhere on the way.
        "status": "0",
        "timestamp": stamp(now()),
        "fields": {
            ACCOUNT_FIELD: order.id,
            # Soʻm, not tiyin (2026-09-22, Дильшод/Paynet certification):
            # unlike PerformTransaction's `amount` param, which the spec
            # fixes in tiyin, GetInformation's is read by a human on a
            # terminal screen before they confirm — tiyin there would show
            # "13000000" for a 130 000 soʻm order.
            "amount": str(_expected_som(order)),
            "currency": order.currency,
        },
    }


async def perform_transaction(
    db: AsyncSession,
    *,
    service_id: int,
    transaction_id: int,
    amount: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Handle ``PerformTransaction``: take the money and settle the order.

    A replay of a ``transactionId`` we already hold answers ``201`` —
    "Транзакция уже существует" — rather than re-echoing the original success
    (2026-09-22, Дильшод/Paynet certification: their own checklist tests this
    exact call twice and expects the error, not a silent second 200). Nothing
    is re-validated or charged twice either way; only the response shape
    changed. The row itself is untouched, so a genuine transport retry that
    never saw our first answer still has ``CheckTransaction``/``GetStatement``
    to confirm the money actually moved.

    Args:
        db: Active session.
        service_id: Paynet's service identifier.
        transaction_id: Paynet's transaction id — the idempotency key.
        amount: Charge in tiyin.
        fields: The account object, carrying ``order_id``.

    Returns:
        ``{"providerTrnId", "fields", "timestamp"}``.

    Raises:
        PaynetError: unknown service, unknown/unpayable order, an amount that
            does not match the order to the tiyin, or (``201``) a
            ``transactionId`` already on file.
    """
    _assert_service(service_id)
    existing = await _find(db, transaction_id)
    if existing is not None:
        raise transaction_already_exists()

    order = await _load_payable_order(db, _account(fields))
    expected = _expected_tiyin(order)
    if amount != expected:
        log.warning(
            "paynet.amount_mismatch",
            order_id=order.id,
            expected_tiyin=expected,
            received_tiyin=amount,
        )
        raise invalid_amount()

    payment = await _ensure_payment(db, order)
    moment = now()
    txn = PaynetTransaction(
        id=new_id(),
        paynet_transaction_id=transaction_id,
        order_id=order.id,
        payment_id=payment.id,
        amount_tiyin=amount,
        service_id=service_id,
        state=STATE_SUCCESS,
        performed_at=moment,
    )
    db.add(txn)
    # Flush before settling so a duplicate ``transactionId`` racing this one
    # trips the unique index here, rather than after the order is already paid.
    #
    # The race is the same duplicate the ``_find`` above catches when the two
    # calls are sequential, so it gets the same answer: ``201``. Without this
    # the loser of the race fell through to the generic handler in ``routes``
    # and answered ``-32603`` — a protocol error for what is, on Paynet's own
    # retry-happy network, an ordinary event.
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_duplicate_transaction(exc):
            raise transaction_already_exists() from exc
        raise
    await pay_svc.settle_provider_payment(
        db, payment=payment, external_event_id=str(transaction_id)
    )
    await db.flush()
    log.info(
        "paynet.performed",
        order_id=order.id,
        provider_trn_id=txn.provider_trn_id,
        amount_tiyin=amount,
    )
    return _performed_result(txn)


async def check_transaction(
    db: AsyncSession, *, service_id: int, transaction_id: int
) -> dict[str, Any]:
    """Handle ``CheckTransaction``: report a transaction's state.

    An id we have never seen is **not** an error here. The spec wants a
    successful envelope carrying ``transactionState: 3``; answering ``203``
    instead makes Paynet read a routine "do you know this?" as a failure, and
    that is the difference between a reconciliation query and an incident.

    Note the inbound ``timestamp`` on this method alone arrives as
    ``EEE MMM dd HH:mm:ss z yyyy`` (``Mon Jun 16 06:12:41 UZT 2021``) rather
    than the format every other method uses. We do not read it — it is Paynet's
    own processing time, informational — so the shape never has to be parsed.

    Args:
        db: Active session.
        service_id: Paynet's service identifier.
        transaction_id: Paynet's transaction id.

    Returns:
        ``{"providerTrnId", "timestamp", "transactionState"}``.
    """
    _assert_service(service_id)
    txn = await _find(db, transaction_id)
    if txn is None:
        # There is no provider id to quote for a transaction that does not
        # exist. Zero is the only honest filler, and ``transactionState: 3``
        # is what Paynet actually reads.
        return {"providerTrnId": 0, "timestamp": stamp(now()), "transactionState": STATE_NOT_FOUND}
    return {
        "providerTrnId": txn.provider_trn_id,
        "timestamp": stamp(txn.cancelled_at or txn.performed_at),
        "transactionState": txn.state,
    }


async def cancel_transaction(
    db: AsyncSession, *, service_id: int, transaction_id: int
) -> dict[str, Any]:
    """Handle ``CancelTransaction``: reverse a settled payment.

    Idempotent: a repeat on an already-cancelled transaction echoes state 2
    rather than erroring. Paynet retries a cancel it never got an answer to,
    so a second call is much more likely to be a retry than a second intent,
    and an error on a retry reads as a reversal that failed.

    **Refused once any goods have shipped.** A single succeeded fulfilment task
    is proof the customer holds a code; clawing the money back would hand them
    the goods for free. Such a case is settled by a human.

    Args:
        db: Active session.
        service_id: Paynet's service identifier.
        transaction_id: Paynet's transaction id.

    Returns:
        ``{"providerTrnId", "timestamp", "transactionState"}``.

    Raises:
        PaynetError: ``203`` unknown transaction, ``306`` goods already
            delivered.
    """
    _assert_service(service_id)
    txn = await _find(db, transaction_id)
    if txn is None:
        raise transaction_not_found()
    if txn.state == STATE_CANCELLED:
        return {
            "providerTrnId": txn.provider_trn_id,
            "timestamp": stamp(txn.cancelled_at or txn.performed_at),
            "transactionState": STATE_CANCELLED,
        }

    order = (await db.execute(select(Order).where(Order.id == txn.order_id))).scalar_one()
    if order.status in _DELIVERED_STATUSES or await _any_goods_delivered(db, txn.order_id):
        log.warning("paynet.cancel_refused_delivered", order_id=order.id, status=order.status)
        raise cancel_refused_delivered()

    payment = await db.get(Payment, txn.payment_id) if txn.payment_id else None
    if payment is None:  # pragma: no cover - written together, SET NULL only on delete
        raise transaction_not_found()

    txn.state = STATE_CANCELLED
    txn.cancelled_at = now()
    txn.updated_at = now()
    await pay_svc.reverse_provider_payment(
        db, payment=payment, external_event_id=f"{transaction_id}:cancel", actor=PROVIDER
    )
    await db.flush()
    log.info("paynet.cancelled", order_id=order.id, provider_trn_id=txn.provider_trn_id)
    return {
        "providerTrnId": txn.provider_trn_id,
        "timestamp": stamp(txn.cancelled_at),
        "transactionState": STATE_CANCELLED,
    }


async def get_statement(
    db: AsyncSession, *, service_id: int, date_from: str, date_to: str
) -> dict[str, Any]:
    """Handle ``GetStatement``: successful transactions in a window.

    Only state 1. Cancelled transactions are deliberately absent — Paynet
    reconciles this list against its own register of *accepted* payments, so a
    cancelled row here reads as money we claim to hold and do not.

    Args:
        db: Active session.
        service_id: Paynet's service identifier.
        date_from: Window start, ``YYYY-MM-dd HH:mm:ss`` at GMT+5.
        date_to: Window end, same format.

    Returns:
        ``{"statements": [...]}``, oldest first.

    Raises:
        PaynetError: unknown service, or a timestamp we cannot parse.
    """
    _assert_service(service_id)
    try:
        start, end = parse_stamp(date_from), parse_stamp(date_to)
    except ValueError as exc:
        raise invalid_datetime() from exc
    rows = (
        await db.execute(
            select(PaynetTransaction)
            .where(
                PaynetTransaction.state == STATE_SUCCESS,
                PaynetTransaction.performed_at >= start,
                PaynetTransaction.performed_at <= end,
            )
            .order_by(PaynetTransaction.performed_at, PaynetTransaction.provider_trn_id)
        )
    ).scalars()
    return {
        "statements": [
            {
                "amount": row.amount_tiyin,
                "transactionId": row.paynet_transaction_id,
                "providerTrnId": row.provider_trn_id,
                "timestamp": stamp(row.performed_at),
            }
            for row in rows
        ]
    }


def _performed_result(txn: PaynetTransaction) -> dict[str, Any]:
    return {
        "providerTrnId": txn.provider_trn_id,
        "fields": {ACCOUNT_FIELD: txn.order_id},
        "timestamp": stamp(txn.performed_at),
    }


def _assert_service(service_id: int) -> None:
    """Refuse a ``serviceId`` we are not contracted under."""
    if service_id != get_settings().paynet_service_id:
        raise unknown_service()


def _account(fields: dict[str, Any]) -> str:
    """Pull the order id out of Paynet's account object."""
    value = fields.get(ACCOUNT_FIELD)
    if not isinstance(value, str) or not value.strip():
        raise order_not_found()
    return value.strip()


def _is_duplicate_transaction(exc: IntegrityError) -> bool:
    """Whether this integrity error is the duplicate-``transactionId`` one.

    Named rather than assumed: the same flush also writes a ``payments`` row
    and an FK to ``orders``, and answering ``201`` to *any* integrity failure
    would tell Paynet "already done" about a transaction we never wrote.
    """
    return UQ_EXTERNAL_TRANSACTION in str(getattr(exc, "orig", exc))


async def _find(db: AsyncSession, transaction_id: int) -> PaynetTransaction | None:
    return (
        await db.execute(
            select(PaynetTransaction).where(
                PaynetTransaction.paynet_transaction_id == transaction_id
            )
        )
    ).scalar_one_or_none()


async def _load_payable_order(
    db: AsyncSession, order_id: str, *, paid_is_not_found: bool = False
) -> Order:
    """Load an order that may still be paid, or say precisely why it may not.

    Args:
        db: Active session.
        order_id: The account field, already extracted and stripped.
        paid_is_not_found: ``GetInformation`` passes ``True`` — an already-paid
            order answers ``302`` there, the same as "no such order", because
            a settled bill has nothing left to show a payer.
            ``PerformTransaction`` leaves this ``False`` and keeps ``201``: a
            client actively trying to pay is owed the specific reason. See the
            comment above :data:`~yupay.modules.paynet.errors.ORDER_NOT_FOUND`
            in ``errors.py``.
    """
    try:
        order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    except Exception as exc:  # a malformed UUID never reaches the database as one
        raise order_not_found() from exc
    if order is None:
        raise order_not_found()
    if order.status in _PAID_STATUSES:
        raise order_not_found() if paid_is_not_found else order_already_paid()
    if order.status != _PAYABLE:
        raise order_not_payable()
    if order.expires_at <= datetime.now(UTC):
        raise order_not_payable()
    return order


def _expected_tiyin(order: Order) -> int:
    """The order's charge in tiyin, refusing anything that is not exact.

    ``total_charged`` is a major-unit ``Decimal`` with 6 dp. A non-integral
    result after ``* 100`` means corrupt order data, and rounding it would
    move money by a fraction nobody authorised.

    This is what ``PerformTransaction``'s ``amount`` is checked against — the
    spec fixes that one in tiyin. ``GetInformation`` shows the same charge in
    soʻm instead; see :func:`_expected_som`.
    """
    raw = order.total_charged * Decimal(100)
    if raw != raw.to_integral_value():
        raise invalid_amount()
    return int(raw)


def _expected_som(order: Order) -> Decimal:
    """The order's charge in soʻm, for ``GetInformation`` alone.

    Routed through :func:`_expected_tiyin` rather than reading
    ``total_charged`` directly, so both methods refuse the same corrupt data
    the same way instead of one silently accepting what the other rejects.
    Dividing the validated tiyin integer back down keeps the result exact —
    ``Decimal(130000) / 100 == Decimal("1300")``, ``Decimal(130050) / 100 ==
    Decimal("1300.5")`` — with no trailing zeros Paynet never asked for.
    """
    return Decimal(_expected_tiyin(order)) / Decimal(100)


async def _ensure_payment(db: AsyncSession, order: Order) -> Payment:
    """Reuse the order's pending Paynet payment, or open one."""
    existing = (
        await db.execute(
            select(Payment).where(
                Payment.order_id == order.id,
                Payment.provider == PROVIDER,
                Payment.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider=PROVIDER,
        status="pending",
        amount=order.total_charged,
        currency=order.currency,
    )
    db.add(payment)
    await db.flush()
    return payment


async def _any_goods_delivered(db: AsyncSession, order_id: str) -> bool:
    """``True`` when at least one item on the order has already shipped.

    A multi-item order can rest at ``fulfilling`` with one code already handed
    over, which the coarse order-status check misses. Mirrors the guard in
    ``payme.service`` — the money question is identical.
    """
    row = (
        await db.execute(
            select(FulfillmentTask.id)
            .where(FulfillmentTask.order_id == order_id, FulfillmentTask.status == "succeeded")
            .limit(1)
        )
    ).first()
    return row is not None


__all__ = [
    "ACCOUNT_FIELD",
    "PROVIDER",
    "TASHKENT",
    "cancel_transaction",
    "check_transaction",
    "get_information",
    "get_statement",
    "parse_stamp",
    "perform_transaction",
    "stamp",
]
