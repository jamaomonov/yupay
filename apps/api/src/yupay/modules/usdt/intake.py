"""Journal confirmed USDT transfers and credit the reservation each one pays (ADR-0104).

One transaction per transfer, owned by the caller: the journal row, the
reservation's ``paid`` and the ledger credit commit together or not at all.
Alerts are returned, not sent — a Telegram call inside a money transaction
would hold the row locks for a network round trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants.deposit import credit_deposit
from yupay.modules.p2p.integrity import violated_constraint
from yupay.modules.usdt.models import UsdtIncoming, UsdtReservation
from yupay.modules.usdt.reservations import CENT, QUARANTINE
from yupay.modules.usdt.tron import Transfer

log = get_logger("yupay.usdt.intake")

Status = Literal["duplicate", "matched", "unmatched", "ignored"]
#: Below this a transfer is dust — address-poisoning spam, never a top-up.
DUST: Final = Decimal("1")
#: A reservation shown a moment before its row committed can still be paid.
_EARLY: Final = timedelta(minutes=1)
_TX_KEY: Final = "uq_usdt_incoming_tx_id"


@dataclass
class IntakeResult:
    """What one transfer turned into, plus alerts for the caller to send after commit."""

    status: Status
    reservation_number: str | None = None
    alerts: list[tuple[str, str]] = field(default_factory=list)


async def _payable(db: AsyncSession, t: Transfer) -> UsdtReservation | None:
    """The one reservation whose amount and window this transfer fits, locked.

    The window is ``[created_at - 1 min, closed_at or expires_at]``, whatever
    the status except ``paid``: the block time is the chain's, so a transfer
    made in time pays its reservation even when we read it after expiry or the
    reseller cancelled after sending. Two windows for one amount cannot overlap
    — the amount stays held through the quarantine, after the window closes.
    """
    end = func.coalesce(UsdtReservation.closed_at, UsdtReservation.expires_at)
    found: UsdtReservation | None = await db.scalar(
        select(UsdtReservation)
        .where(
            UsdtReservation.amount_usdt == t.amount,
            UsdtReservation.status != "paid",
            UsdtReservation.created_at - _EARLY <= t.block_at,
            or_(end >= t.block_at, UsdtReservation.status == "pending"),
        )
        .order_by(UsdtReservation.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if found is None or (found.status == "pending" and found.expires_at < t.block_at):
        return None
    return found


async def ingest(db: AsyncSession, t: Transfer, *, received_at: datetime) -> IntakeResult:
    """Journal one transfer and credit the reservation it pays, if any.

    Args:
        db: Session. The caller commits, then sends ``alerts``.
        t: A transfer already checked by ``tron.parse_transfer``.
        received_at: When we read it.

    Returns:
        ``duplicate`` when this transaction id is already journaled; otherwise
        the outcome and any alerts.
    """
    row = UsdtIncoming(
        id=new_id(),
        tx_id=t.tx_id,
        from_address=t.from_address,
        to_address=t.to_address,
        amount_usdt=t.amount,
        block_at=t.block_at,
        result="ignored",
        received_at=received_at,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        if violated_constraint(exc, (_TX_KEY,)) is None:
            raise
        return IntakeResult("duplicate")

    if t.amount < DUST:
        log.info("usdt.dust", amount=str(t.amount))
        return IntakeResult("ignored")

    reservation = await _payable(db, t) if t.amount == t.amount.quantize(CENT) else None
    if reservation is None:
        row.result = "unmatched"
        await db.flush()
        log.info("usdt.unmatched", amount=str(t.amount), tx_id=t.tx_id)
        return IntakeResult(
            "unmatched",
            alerts=[
                (
                    "usdt_unmatched",
                    f"USDT: перевод {t.amount.normalize():f} USDT не совпал ни с одной заявкой — "
                    "разберите в админке (USDT → журнал)",
                )
            ],
        )

    await credit_deposit(
        db,
        merchant_id=reservation.merchant_id,
        amount=reservation.amount_usdt,
        actor="usdt",
        idempotency_key=f"usdt:{reservation.id}",
        order_id=None,
        note=f"USDT · {reservation.number}",
    )
    # The amount stays held through the quarantine: an accidental second
    # transfer of it must land unmatched, not pay whoever reserves it next.
    closed = reservation.closed_at or received_at
    reservation.status = "paid"
    reservation.closed_at = closed
    reservation.quarantine_until = max(received_at, closed) + QUARANTINE
    reservation.incoming_id = row.id
    reservation.holds_amount = True
    row.result, row.reservation_id = "matched", reservation.id
    await db.flush()
    log.info("usdt.matched", number=reservation.number, amount_usdt=str(reservation.amount_usdt))
    return IntakeResult("matched", reservation_number=reservation.number)


__all__ = ["DUST", "IntakeResult", "ingest"]
