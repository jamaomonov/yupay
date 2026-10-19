"""File a @HUMOcardbot notification and, if it pays a reservation, credit it (spec §5.4-5.5).

One transaction, owned by the caller: the journal row, the reservation's
``paid`` and the ledger credit commit together or not at all. Alerts are
returned, not sent — a Telegram call inside a money transaction would hold the
row locks for a network round trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants.deposit import credit_deposit
from yupay.modules.p2p.integrity import violated_constraint
from yupay.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation, P2PSettings
from yupay.modules.p2p.parsing import ParsedNotification, parse_humo
from yupay.modules.p2p.reservations import QUARANTINE
from yupay.modules.p2p.settings import load_settings

log = get_logger("yupay.p2p.intake")

Status = Literal["dropped", "duplicate", "matched", "unmatched", "ignored"]
_MESSAGE_KEY = "uq_p2p_incoming_message"


@dataclass
class IntakeResult:
    """What one update turned into.

    Attributes:
        status: ``dropped`` (not from the HUMO bot), ``duplicate`` (already
            journaled), ``matched`` (credited a reservation), ``unmatched`` (a
            credit nobody was waiting for) or ``ignored`` (debit, unparsed, or a
            card that is not ours).
        reservation_number: The paid reservation's number when ``matched``.
        alerts: ``(kind, text)`` pairs for the caller to send after commit.
    """

    status: Status
    reservation_number: str | None = None
    alerts: list[tuple[str, str]] = field(default_factory=list)


def _humo_message(update: dict[str, Any], settings: P2PSettings) -> dict[str, Any] | None:
    """Return the business message only if it came from the HUMO bot, unforwarded.

    It must also arrive through the owner's pinned Business connection: anyone
    with Telegram Premium can connect the bot to *their* account and feed it
    look-alike HUMO messages. Nothing pinned (or no HUMO id) drops everything.
    """
    msg = update.get("business_message")
    humo_id = settings.humo_bot_user_id
    pinned = settings.business_connection_id
    if not isinstance(msg, dict) or humo_id is None or not pinned:
        return None
    if msg.get("business_connection_id") != pinned:
        return None
    sender = (msg.get("from") or {}).get("id")
    chat = (msg.get("chat") or {}).get("id")
    if sender != humo_id or chat != humo_id or msg.get("forward_origin"):
        return None
    return msg


def _track_connection(settings: P2PSettings, connection: dict[str, Any]) -> None:
    """Pin the owner's Business connection on enable; unpin it on disable.

    Logs connection health only — never the user id, never a name.
    """
    user_id = (connection.get("user") or {}).get("id")
    conn_id = connection.get("id")
    enabled = connection.get("is_enabled") is True
    owner = settings.owner_telegram_user_id
    is_owner = owner is not None and user_id == owner
    if is_owner and enabled and isinstance(conn_id, str) and conn_id:
        settings.business_connection_id = conn_id
    elif not enabled and conn_id is not None and conn_id == settings.business_connection_id:
        settings.business_connection_id = None
    rights = connection.get("rights")
    log.info(
        "p2p.business_connection",
        is_enabled=connection.get("is_enabled"),
        rights=sorted(k for k, v in rights.items() if v) if isinstance(rights, dict) else None,
        owner=is_owner,
    )


async def _chain_ok(
    db: AsyncSession, p: ParsedNotification, connection_id: str, message_id: int
) -> bool | None:
    """Whether the previous balance plus this movement equals this balance.

    The predecessor is the same card's row with the greatest Telegram message
    id below this one on the same Business connection. Message ids are the
    chat's own order, so same-minute bank times and out-of-order delivery do
    not pick the wrong row; a message that arrives before its predecessor has
    no predecessor yet and is not judged (``None``).
    """
    if p.kind not in ("credit", "debit") or p.balance_after is None or p.amount is None:
        return None
    prev = await db.scalar(
        select(P2PIncoming)
        .where(
            P2PIncoming.card_last4 == p.card_last4,
            P2PIncoming.business_connection_id == connection_id,
            P2PIncoming.telegram_message_id < message_id,
            P2PIncoming.balance_after.is_not(None),
        )
        .order_by(P2PIncoming.telegram_message_id.desc())
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
    paid_at = p.bank_time or received_at
    reservation: P2PReservation | None = await db.scalar(
        select(P2PReservation)
        .join(P2PCard, P2PCard.id == P2PReservation.card_id)
        .where(
            P2PCard.pan_last4 == p.card_last4,
            P2PCard.active.is_(True),
            P2PReservation.amount_uzs == int(p.amount),
            P2PReservation.status.in_(("pending", "expired")),
            P2PReservation.holds_amount.is_(True),
            # Minute-precision bank time: a transfer cannot pay a reservation
            # that did not exist yet, nor one whose window had closed.
            P2PReservation.created_at < paid_at + timedelta(minutes=1),
            P2PReservation.expires_at >= paid_at,
        )
        .order_by(P2PReservation.created_at)
        .limit(1)
        .with_for_update(of=P2PReservation)
    )
    return reservation


async def _foreign_card(db: AsyncSession, last4: str | None) -> bool:
    """True when no card of ours, active or not, ends in ``last4``.

    The bot's feed is shared with csmarket through a relay (runbook §2), and the
    owner's HUMO chat reports their card too. Such a row is journaled as
    ``ignored``: it is not money for the operator to resolve, and it must never
    pay a reservation of the same amount. An inactive card of ours still counts
    as ours, so a late transfer to it stays ``unmatched`` as before.
    """
    if last4 is None:
        return False
    count = await db.scalar(
        select(func.count()).select_from(P2PCard).where(P2PCard.pan_last4 == last4)
    )
    return not count


async def _ambiguous_card(db: AsyncSession, last4: str | None) -> bool:
    """True when more than one active card ends in ``last4`` (never auto-match)."""
    count = await db.scalar(
        select(func.count())
        .select_from(P2PCard)
        .where(P2PCard.pan_last4 == last4, P2PCard.active.is_(True))
    )
    return (count or 0) > 1


async def _settle_order(db: AsyncSession, reservation: P2PReservation, *, incoming_id: str) -> bool:
    """Mark the storefront payment behind an order reservation succeeded (ADR-0097).

    The payment row is the one ``payments.service.create_intent`` wrote with
    ``external_id = "p2p:<number>"``. Settling goes through
    ``settle_provider_payment`` — the same chokepoint Payme's
    ``PerformTransaction`` uses — so a transfer flips the order to ``paid``,
    starts fulfilment and, for an order that already expired, takes the
    late-payment path rather than a second one of its own.

    Returns:
        Whether a payment was found and settled. ``False`` means the
        reservation exists but no payment references it — a state nothing
        writes today, reported rather than guessed around.
    """
    from yupay.modules.payments.models import Payment
    from yupay.modules.payments.service import settle_provider_payment

    payment = await db.scalar(
        select(Payment).where(
            Payment.provider == "p2p", Payment.external_id == f"p2p:{reservation.number}"
        )
    )
    if payment is None:
        log.warning("p2p.order_payment_missing", number=reservation.number)
        return False
    await settle_provider_payment(db, payment=payment, external_event_id=f"p2p:{incoming_id}")
    log.info("p2p.order_paid", number=reservation.number, order_id=payment.order_id)
    return True


async def _credit(
    db: AsyncSession,
    row: P2PIncoming,
    parsed: ParsedNotification,
    received_at: datetime,
    result: IntakeResult,
) -> None:
    """Match a credit to a reservation and book it, or mark it unmatched."""
    if await _ambiguous_card(db, parsed.card_last4):
        row.result = "unmatched"
        result.status = "unmatched"
        result.alerts.append(
            (
                "p2p_ambiguous_card",
                f"P2P: несколько активных карт с окончанием *{parsed.card_last4} — "
                "зачисление не выполнено автоматически",
            )
        )
        return
    reservation = await _payable(db, parsed, received_at)
    if reservation is None:
        row.result = "unmatched"
        result.status = "unmatched"
        log.info("p2p.unmatched", amount=str(parsed.amount), card_last4=parsed.card_last4)
        return
    if reservation.purpose == "order":
        if not await _settle_order(db, reservation, incoming_id=row.id):
            row.result = "unmatched"
            result.status = "unmatched"
            result.alerts.append(
                (
                    "p2p_order_payment_missing",
                    f"P2P: перевод совпал с резервацией {reservation.number} заказа, "
                    "но платежа под неё нет — зачисление не выполнено",
                )
            )
            return
    elif reservation.merchant_id is not None:
        await credit_deposit(
            db,
            merchant_id=reservation.merchant_id,
            amount=reservation.amount_usd,
            actor="p2p",
            idempotency_key=f"p2p:{reservation.id}",
            order_id=None,
            note=f"P2P · {reservation.number}",
        )
    else:
        row.result = "unmatched"
        result.status = "unmatched"
        log.info("p2p.unmatched", amount=str(parsed.amount), card_last4=parsed.card_last4)
        return
    # The amount stays held for the quarantine: a payer's accidental second
    # transfer must land unmatched, not pay whoever reserves the same sum next.
    reservation.status = "paid"
    reservation.closed_at = received_at
    reservation.quarantine_until = received_at + QUARANTINE
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
    connection = update.get("business_connection")
    if isinstance(connection, dict):
        _track_connection(settings, connection)
        await db.flush()
        return IntakeResult("dropped")
    msg = _humo_message(update, settings)
    if msg is None:
        return IntakeResult("dropped")
    message_id = msg.get("message_id")
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        # Field name only: the message text is PII and the id is absent or junk.
        log.warning("p2p.malformed_update", field="message_id")
        return IntakeResult("dropped")

    text = str(msg.get("text") or "")
    parsed = parse_humo(text)
    row = P2PIncoming(
        id=new_id(),
        business_connection_id=str(msg.get("business_connection_id") or ""),
        telegram_message_id=message_id,
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
    row.chain_ok = await _chain_ok(db, parsed, row.business_connection_id, message_id)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        if violated_constraint(exc, (_MESSAGE_KEY,)) is None:
            raise
        return IntakeResult("duplicate")

    result = IntakeResult("ignored")
    if await _foreign_card(db, parsed.card_last4):
        log.info("p2p.foreign_card", kind=parsed.kind)
        return result
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
