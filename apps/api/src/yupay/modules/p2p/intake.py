"""File a @HUMOcardbot notification and, if it pays a reservation, credit it (spec §5.4-5.5).

One transaction, owned by the caller: the journal row, the reservation's
``paid`` and the ledger credit commit together or not at all. Alerts are
returned, not sent — a Telegram call inside a money transaction would hold the
row locks for a network round trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants.deposit import credit_deposit
from yupay.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation
from yupay.modules.p2p.parsing import ParsedNotification, parse_humo
from yupay.modules.p2p.settings import load_settings

log = get_logger("yupay.p2p.intake")

Status = Literal["dropped", "duplicate", "matched", "unmatched", "ignored"]


@dataclass
class IntakeResult:
    """What one update turned into.

    Attributes:
        status: ``dropped`` (not from the HUMO bot), ``duplicate`` (already
            journaled), ``matched`` (credited a reservation), ``unmatched`` (a
            credit nobody was waiting for) or ``ignored`` (debit or unparsed).
        reservation_number: The paid reservation's number when ``matched``.
        alerts: ``(kind, text)`` pairs for the caller to send after commit.
    """

    status: Status
    reservation_number: str | None = None
    alerts: list[tuple[str, str]] = field(default_factory=list)


def _humo_message(update: dict[str, Any], humo_id: int | None) -> dict[str, Any] | None:
    """Return the business message only if it came from the HUMO bot, unforwarded."""
    msg = update.get("business_message")
    if not isinstance(msg, dict) or humo_id is None:
        return None
    sender = (msg.get("from") or {}).get("id")
    chat = (msg.get("chat") or {}).get("id")
    if sender != humo_id or chat != humo_id or msg.get("forward_origin"):
        return None
    return msg


async def _chain_ok(db: AsyncSession, p: ParsedNotification) -> bool | None:
    """Whether the previous balance plus this movement equals this balance."""
    if p.kind not in ("credit", "debit") or p.balance_after is None or p.amount is None:
        return None
    prev = await db.scalar(
        select(P2PIncoming)
        .where(P2PIncoming.card_last4 == p.card_last4, P2PIncoming.balance_after.is_not(None))
        .order_by(P2PIncoming.bank_time.desc(), P2PIncoming.received_at.desc())
        .limit(1)
    )
    if prev is None or prev.balance_after is None:
        return None
    signed = p.amount if p.kind == "credit" else -p.amount
    return prev.balance_after + signed == p.balance_after


async def _payable(
    db: AsyncSession, p: ParsedNotification, received_at: datetime
) -> P2PReservation | None:
    """Lock the reservation this credit pays, if exactly one is waiting.

    Accepts an ``expired`` row whose quarantine still holds the amount (a late
    delivery of an on-time transfer); ``expires_at >= paid_at`` keeps genuinely
    late transfers out. ``bank_time`` has minute precision, so sub-minute
    lateness is accepted.
    """
    if p.kind != "credit" or p.amount is None or p.amount != p.amount.to_integral_value():
        return None
    card = await db.scalar(select(P2PCard).where(P2PCard.pan_last4 == p.card_last4))
    if card is None:
        return None
    paid_at = p.bank_time or received_at
    reservation: P2PReservation | None = await db.scalar(
        select(P2PReservation)
        .where(
            P2PReservation.card_id == card.id,
            P2PReservation.amount_uzs == int(p.amount),
            P2PReservation.status.in_(("pending", "expired")),
            P2PReservation.holds_amount.is_(True),
            P2PReservation.expires_at >= paid_at,
        )
        .order_by(P2PReservation.created_at)
        .limit(1)
        .with_for_update()
    )
    return reservation


async def _credit(
    db: AsyncSession,
    row: P2PIncoming,
    parsed: ParsedNotification,
    received_at: datetime,
    result: IntakeResult,
) -> None:
    """Match a credit to a reservation and book it, or mark it unmatched."""
    reservation = await _payable(db, parsed, received_at)
    if reservation is None or reservation.merchant_id is None:
        row.result = "unmatched"
        result.status = "unmatched"
        log.info("p2p.unmatched", amount=str(parsed.amount), card_last4=parsed.card_last4)
        return
    await credit_deposit(
        db,
        merchant_id=reservation.merchant_id,
        amount=reservation.amount_usd,
        actor="p2p",
        idempotency_key=f"p2p:{reservation.id}",
        order_id=None,
        note=f"P2P · {reservation.number}",
    )
    reservation.status = "paid"
    reservation.holds_amount = False
    reservation.closed_at = received_at
    reservation.quarantine_until = None
    reservation.incoming_id = row.id
    row.result, row.reservation_id = "matched", reservation.id
    result.status, result.reservation_number = "matched", reservation.number
    log.info("p2p.matched", number=reservation.number, amount_uzs=reservation.amount_uzs)


async def ingest_update(
    db: AsyncSession, update: dict[str, Any], *, received_at: datetime
) -> IntakeResult:
    """Journal one Telegram update and credit the reservation it pays, if any.

    Args:
        db: Session. The caller commits, then sends ``alerts``.
        update: The decoded Telegram update.
        received_at: When we received it.

    Returns:
        The outcome and any alerts to send after commit.
    """
    settings = await load_settings(db)
    msg = _humo_message(update, settings.humo_bot_user_id)
    if msg is None:
        return IntakeResult("dropped")

    text = str(msg.get("text") or "")
    parsed = parse_humo(text)
    row = P2PIncoming(
        id=new_id(),
        business_connection_id=str(msg.get("business_connection_id") or ""),
        telegram_message_id=int(msg["message_id"]),
        kind=parsed.kind,
        amount_uzs=parsed.amount,
        source_text=(parsed.source or "")[:128] or None,
        card_last4=parsed.card_last4,
        bank_time=parsed.bank_time,
        balance_after=parsed.balance_after,
        raw_text=text,
        result="ignored",
        received_at=received_at,
    )
    row.chain_ok = await _chain_ok(db, parsed)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return IntakeResult("duplicate")

    result = IntakeResult("ignored")
    if parsed.kind == "unparsed":
        result.alerts.append(
            (
                "p2p_unparsed",
                f"P2P: не удалось разобрать уведомление HUMO (id {row.telegram_message_id})",
            )
        )
    if row.chain_ok is False:
        result.alerts.append(
            (
                "p2p_chain_break",
                f"P2P: разрыв цепочки балансов по *{row.card_last4} — "
                "возможно пропущено уведомление",
            )
        )
    if parsed.kind == "credit":
        await _credit(db, row, parsed, received_at, result)
    await db.flush()
    return result


__all__ = ["IntakeResult", "ingest_update"]
