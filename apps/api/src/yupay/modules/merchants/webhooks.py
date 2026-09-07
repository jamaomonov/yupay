"""The webhook outbox's **producer** — a delivery row, written with its cause.

Spec §10, M3a Task 3. Task 1 built the tables, Task 2 the client that may
safely connect to a merchant's address, and Task 4 drains what this module
writes. Nothing here talks to a merchant; it puts work in a queue.

## One transaction, or none

:func:`enqueue` inserts into ``merchant_webhook_deliveries`` **in the caller's
transaction** and issues the ``pg_notify`` inside it too, exactly the shape
``fulfillment.service.start_for_order`` uses for its own queue (ADR-0064).
Postgres delivers a NOTIFY on COMMIT and drops it on ROLLBACK, so a nudge can
neither outrun the fact that caused it nor survive that fact being undone. An
order that rolls back has no event, and a merchant is never told about a sale
that did not happen.

Task 4's poll tick covers a nudge lost to a worker restart, so nothing here
has to care about a listener being down.

## A courtesy may never fail money

An order is money; a webhook is a courtesy. The insert therefore runs inside a
SAVEPOINT and an ``IntegrityError``/``DataError`` from it is **swallowed** —
logged at ``error`` with the merchant and order — rather than allowed to abort
the transaction that just debited a deposit. Two halves make that safe rather
than sloppy:

- the swallow is *narrow*. Only the two exception types a bad row raises are
  caught; a broken session, a lost connection or a programming error still
  propagate, because hiding those behind a plausible commit is how a silent
  outage starts.
- it is a SAVEPOINT, not a bare ``try``. A failed flush poisons a session
  until something rolls back, and rolling back the *caller's* transaction is
  the exact harm this rule exists to prevent; ``begin_nested`` undoes only
  what this function wrote. The caller's own pending writes are flushed
  **before** the savepoint opens so they can never be inside it.

Every column this writes to is NOT NULL or length-bounded on purpose (Task 1),
so a producer that forgets one fails loudly at insert instead of quietly at
delivery — which is why the swallow can be this narrow and still not hide a
real bug: it hides one delivery, never one order.

## What a payload may contain

`order.status_changed` carries the order's public identity and its new status,
and **nothing from the delivery artifact**. A voucher code is a bearer
instrument and a webhook body is written to the receiver's logs wholesale, so
the code is fetched over the authenticated read
(``GET /merchant/v1/orders/{merchant_order_id}``) and never pushed. The tests
assert the payload's *exact key set* rather than the absence of one known
name — that is what stops a future field addition from smuggling a value into
a body somebody else logs.

Money is a **string** at two decimals, through the same annotations
``/merchant/v1`` uses (``machine_schemas.UsdAmount`` / ``UsdBalance``), so a
webhook body and the read endpoint cannot disagree about the shape of a
balance. JSONB has no ``Decimal`` and a float would round it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.exc import DataError, IntegrityError

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants.machine_schemas import UsdAmount, UsdBalance
from yupay.modules.merchants.models import MerchantWebhook, MerchantWebhookDelivery

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.orders.models import Order

log = get_logger("yupay.merchants.webhooks")

#: The LISTEN/NOTIFY channel the delivery worker wakes on. One constant, in
#: one place: Task 4's ``ListenerManager`` imports **this name**, because a
#: channel spelled twice is a queue nobody drains and no test fails.
WEBHOOK_QUEUE_CHANNEL: Final = "merchant_webhook_queue"

#: An order's status moved. Its payload is the order's public identity plus
#: the new status — never the artifact.
EVENT_ORDER_STATUS_CHANGED: Final = "order.status_changed"

#: Support credited the merchant's deposit.
EVENT_BALANCE_CREDITED: Final = "balance.credited"

#: The complete v1 vocabulary (spec §10). ``merchant_webhook_deliveries``
#: deliberately carries no CHECK on ``event_type`` — enforcing it here keeps
#: adding a third event a code change rather than a migration on a table that
#: only grows.
EVENT_TYPES: Final[frozenset[str]] = frozenset({EVENT_ORDER_STATUS_CHANGED, EVENT_BALANCE_CREDITED})

_AMOUNT = TypeAdapter(UsdAmount)
_BALANCE = TypeAdapter(UsdBalance)


async def enqueue(
    db: AsyncSession, *, merchant_id: str, event_type: str, payload: dict[str, Any]
) -> str | None:
    """Queue one delivery for a merchant, in the caller's transaction.

    A merchant with no webhook row, and one whose row is disabled, are the
    **same outcome — nothing is written**. The outbox holds only deliverable
    work; a row Task 4 would have to skip is a row that makes the backlog
    meaningless and the cabinet's delivery log a lie.

    Args:
        db: Session. The caller owns the transaction, and this function must
            not end it — see the module docstring on the savepoint.
        merchant_id: Whose endpoint to address.
        event_type: One of :data:`EVENT_TYPES`.
        payload: Exactly the JSON body Task 4 will sign and POST. Must carry
            no material from a delivery artifact.

    Returns:
        The new delivery's id, or ``None`` when nothing was queued — no hook,
        a disabled hook, or an insert that failed and was swallowed. The
        caller cannot act differently on those three and is not asked to.

    Raises:
        ValueError: ``event_type`` is outside the v1 vocabulary. A caller bug,
            not a runtime condition: every call site passes a constant from
            this module.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown merchant webhook event type: {event_type!r}")

    hook = (
        await db.execute(
            select(MerchantWebhook).where(
                MerchantWebhook.merchant_id == merchant_id,
                MerchantWebhook.disabled_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if hook is None:
        return None

    # Everything the caller has pending reaches the database BEFORE the
    # savepoint opens, so rolling ours back can never take one of their writes
    # with it — a rollback to a savepoint would undo the row in Postgres while
    # the ORM went on believing it persisted.
    await db.flush()

    delivery_id = new_id()
    try:
        async with db.begin_nested():
            db.add(
                MerchantWebhookDelivery(
                    id=delivery_id,
                    merchant_id=merchant_id,
                    # Snapshot, never a join: setting a URL edits the hook row
                    # in place, so a join would re-attribute this delivery's
                    # eventual response to whatever address is current.
                    url=hook.url,
                    event_type=event_type,
                    payload=payload,
                )
            )
            await db.flush()
            # Same shape as ``fulfillment.service``'s: the NOTIFY rides this
            # transaction, carrying the row's id so Task 4 can go straight at
            # it. A rolled-back savepoint discards the notification with the
            # row — Postgres tracks them per subtransaction.
            await db.execute(
                text("SELECT pg_notify(:channel, :id)"),
                {"channel": WEBHOOK_QUEUE_CHANNEL, "id": delivery_id},
            )
    except (IntegrityError, DataError) as exc:
        # Narrow on purpose (module docstring): a bad delivery row must not
        # roll back a paid order, and anything that is not a bad delivery row
        # must not be hidden.
        _log_enqueue_failure(
            exc,
            merchant_id=merchant_id,
            event_type=event_type,
            delivery_id=delivery_id,
            # Read out of the payload because that is where an order event's
            # identity lives; absent, and ``None``, for a balance event.
            order_id=payload.get("order_id"),
        )
        return None
    return delivery_id


def _log_enqueue_failure(
    exc: IntegrityError | DataError,
    *,
    merchant_id: str,
    event_type: str,
    delivery_id: str,
    order_id: str | None,
) -> None:
    """Report a swallowed insert loudly, without the driver's message.

    Not ``log.exception`` and not ``str(exc)``, for the reason
    ``core.outbound._log_broken`` gives about its own chain: the text is not
    as harmless as it looks. A ``NotNullViolation`` renders ``DETAIL: Failing
    row contains (…)`` — the whole row, including the ``url`` snapshot, which
    is sized to hold a path with a token in it (``models.WEBHOOK_URL_MAX``).
    Logging it would put a merchant's endpoint credential in Loki over a
    courtesy failure.

    The exception type and the SQLSTATE are enough to find this, because
    reaching here is **our** bug: every column on the row is NOT NULL or
    length-bounded on purpose, so there is no merchant input that can cause
    it and no operator action that answers it.

    Args:
        exc: The swallowed insert failure.
        merchant_id: Whose delivery was lost.
        event_type: Which event was lost.
        delivery_id: The id the row would have had.
        order_id: The order behind the event, when there is one.
    """
    log.error(
        "merchant_webhook.enqueue_failed",
        merchant_id=merchant_id,
        event_type=event_type,
        delivery_id=delivery_id,
        order_id=order_id,
        failure=type(exc).__name__,
        sqlstate=getattr(exc.orig, "sqlstate", None),
    )


async def on_order_status_changed(db: AsyncSession, order: Order) -> str | None:
    """Queue ``order.status_changed`` for a merchant order; ignore any other.

    Called from ``orders.service.on_order_status_changed``, the one seam every
    status transition in the system goes through.

    Args:
        db: Session. The caller owns the transaction.
        order: The order, with its new ``status`` and ``updated_at`` already
            set — both are read straight onto the wire.

    Returns:
        The new delivery's id, or ``None`` — including for every retail order,
        which has no merchant to tell.
    """
    if order.merchant_id is None:
        return None
    return await enqueue(
        db,
        merchant_id=order.merchant_id,
        event_type=EVENT_ORDER_STATUS_CHANGED,
        payload={
            # The reseller's own id for this order — the handle their back
            # office keys on, and the only one they can correlate without a
            # lookup. Stored in ``idempotency_key``; never NULL on a merchant
            # order (``POST /merchant/v1/orders`` requires it), and defaulted
            # rather than allowed to serialise as ``null`` because a machine
            # contract that hands out two shapes for one field is a bug on the
            # receiver's side, not ours.
            "merchant_order_id": order.idempotency_key or "",
            "order_id": order.id,
            "status": order.status,
            "at": order.updated_at.isoformat(),
        },
    )


async def on_balance_credited(
    db: AsyncSession, *, merchant_id: str, amount: Decimal, balance: Decimal
) -> str | None:
    """Queue ``balance.credited`` after support tops a deposit up.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose deposit moved.
        amount: What was credited. Positive.
        balance: The deposit balance after the credit.

    Returns:
        The new delivery's id, or ``None``.
    """
    return await enqueue(
        db,
        merchant_id=merchant_id,
        event_type=EVENT_BALANCE_CREDITED,
        payload={
            "amount_usd": str(_AMOUNT.validate_python(amount)),
            "balance_usd": str(_BALANCE.validate_python(balance)),
        },
    )


__all__ = [
    "EVENT_BALANCE_CREDITED",
    "EVENT_ORDER_STATUS_CHANGED",
    "EVENT_TYPES",
    "WEBHOOK_QUEUE_CHANNEL",
    "enqueue",
    "on_balance_credited",
    "on_order_status_changed",
]
