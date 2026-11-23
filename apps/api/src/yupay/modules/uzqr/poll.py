"""Poll every open UzQR invoice and act on what it says (ADR-0106).

UzQR has no callback, so this is the only way a QR payment is ever booked.

**Open** means UzQR has not confirmed the invoice closed — not that our
payment is pending. The two part ways when an order expires: the expiry sweep
cancels the order's pending payments (``orders.service._cascade_cancel_open_payments``)
while the invoice stays payable at UzQR for 24 hours, and a payer who scanned
the QR a minute earlier can still pay it. So a payment leaves this poll only
when ``extra_metadata["uzqr_closed"]`` is set, and that is set only on UzQR's
word: a rejected or vanished invoice (3001), or a cancel UzQR accepted.

Per open invoice, one tick:

* **paid** → ``settle_provider_payment`` (the Payme-callback chokepoint: the
  order goes ``paid`` and fulfilment starts; an order that expired or was
  cancelled meanwhile takes the late-payment path there, which holds or
  credits it for an operator).
* **rejected**, or **gone** (3001) → closed; a still-pending payment is cancelled.
* **still pending** while the order's window is over, or our payment is no
  longer pending → cancel at UzQR, then close. If UzQR answers "already paid"
  (3002) the payer won the race: the status is read again and the payment booked.

The HTTP call to UzQR is made with no database session open, so a slow UzQR
never holds a pool connection. Every write re-reads the payment under its row
lock (inside the ``payments.service`` helpers), so a tick that overlaps a
previous one cannot book twice.

A UzQR outage is not an error to act on: nothing changes and the next tick
asks again. The scheduler job alerts when that lasts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.orders.models import Order
from yupay.modules.payments import service as payments
from yupay.modules.payments.models import Payment
from yupay.modules.uzqr import client

log = get_logger("yupay.uzqr.poll")

#: One tick looks at no more than this many invoices; the oldest first.
BATCH: Final = 200
#: UzQR keeps an invoice payable for 24 h (spec §1.4.4); an hour of margin.
INVOICE_LIFETIME: Final = timedelta(hours=25)
CLOSED_KEY: Final = "uzqr_closed"

SessionFactory = Callable[[], Any]


@dataclass
class PollResult:
    """What one tick did, for the job's log line and its outage alert."""

    checked: int = 0
    paid: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    unavailable: int = 0


@dataclass(frozen=True)
class _Open:
    payment_id: str
    invoice_id: str
    #: Nobody should pay this any more: the order's window is over or our
    #: payment already left ``pending``.
    stale: bool


def _open_filter() -> Any:
    return (
        (Payment.provider == "uzqr")
        & Payment.status.in_(("pending", "cancelled"))
        & Payment.extra_metadata[CLOSED_KEY].as_boolean().is_not(True)
    )


async def _open_invoices(sessions: SessionFactory) -> list[_Open]:
    t = now()
    async with sessions() as db:
        rows = (
            await db.execute(
                select(
                    Payment.id,
                    Payment.status,
                    Payment.extra_metadata,
                    Order.status,
                    Order.expires_at,
                )
                .join(Order, Order.id == Payment.order_id)
                .where(_open_filter(), Payment.created_at > t - INVOICE_LIFETIME)
                .order_by(Payment.created_at)
                .limit(BATCH)
            )
        ).all()
    out: list[_Open] = []
    for payment_id, payment_status, meta, order_status, expires_at in rows:
        invoice_id = (meta or {}).get("invoice_id")
        if not isinstance(invoice_id, str):
            log.error("uzqr.poll.no_invoice_id", payment_id=payment_id)
            continue
        stale = payment_status != "pending" or order_status != "pending_payment" or expires_at <= t
        out.append(_Open(payment_id, invoice_id, stale))
    return out


async def _settle(sessions: SessionFactory, payment_id: str, pay_id: str) -> None:
    async with sessions() as db:
        payment = await db.get(Payment, payment_id)
        if payment is None:
            return
        # The service re-reads the row under lock (``refresh``), which would
        # discard anything set before it: mark the payment afterwards.
        await payments.settle_provider_payment(
            db, payment=payment, external_event_id=f"uzqr:{pay_id}"
        )
        payment.extra_metadata = {
            **(payment.extra_metadata or {}),
            "pay_id": pay_id,
            CLOSED_KEY: True,
        }
        await db.commit()


async def _close(sessions: SessionFactory, payment_id: str) -> None:
    """UzQR confirmed nobody can pay this invoice: stop polling, cancel if pending."""
    async with sessions() as db:
        payment = await db.get(Payment, payment_id)
        if payment is None:
            return
        await payments.cancel_pending_provider_payment(db, payment=payment, actor="uzqr")
        payment.extra_metadata = {**(payment.extra_metadata or {}), CLOSED_KEY: True}
        await db.commit()


async def _cancel_at_uzqr(sessions: SessionFactory, item: _Open, result: PollResult) -> None:
    try:
        await client.cancel_invoice(item.invoice_id)
    except client.UzqrError as exc:
        if exc.code == client.INVOICE_NOT_FOUND:
            await _close(sessions, item.payment_id)
            result.closed.append(item.payment_id)
            return
        if exc.code != client.INVOICE_ALREADY_PAID:
            raise
        # The payer beat the clock. Read the pay_id and book it.
        status = await client.invoice_status(item.invoice_id)
        if status.status == client.STATUS_PAID and status.pay_id:
            await _settle(sessions, item.payment_id, status.pay_id)
            result.paid.append(item.payment_id)
        return
    await _close(sessions, item.payment_id)
    result.closed.append(item.payment_id)


async def _one(sessions: SessionFactory, item: _Open, result: PollResult) -> None:
    try:
        status = await client.invoice_status(item.invoice_id)
    except client.UzqrError as exc:
        if exc.code != client.INVOICE_NOT_FOUND:
            raise
        # Past UzQR's 24 h, or never created: nobody can pay it now.
        await _close(sessions, item.payment_id)
        result.closed.append(item.payment_id)
        return
    if status.status == client.STATUS_PAID and status.pay_id:
        await _settle(sessions, item.payment_id, status.pay_id)
        result.paid.append(item.payment_id)
    elif status.status == client.STATUS_REJECTED:
        await _close(sessions, item.payment_id)
        result.closed.append(item.payment_id)
    elif item.stale:
        await _cancel_at_uzqr(sessions, item, result)


async def poll_once(sessions: SessionFactory) -> PollResult:
    """One pass over the open invoices. One bad invoice never stops the rest."""
    result = PollResult()
    for item in await _open_invoices(sessions):
        result.checked += 1
        try:
            await _one(sessions, item, result)
        except client.UzqrUnavailableError:
            result.unavailable += 1
        except client.UzqrError as exc:
            result.unavailable += 1
            log.warning("uzqr.poll.refused", payment_id=item.payment_id, code=exc.code)
    if result.paid or result.closed:
        log.info(
            "uzqr.poll.done",
            checked=result.checked,
            paid=len(result.paid),
            closed=len(result.closed),
        )
    return result


async def open_count(db: AsyncSession) -> int:
    """How many invoices are still open — the outage alert's "is anyone affected"."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Payment)
            .where(_open_filter(), Payment.created_at > now() - INVOICE_LIFETIME)
        )
        or 0
    )


__all__ = ["BATCH", "CLOSED_KEY", "INVOICE_LIFETIME", "PollResult", "open_count", "poll_once"]
