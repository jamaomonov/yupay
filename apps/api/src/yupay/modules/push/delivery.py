"""Sending queued pushes (worker) and reading Expo's receipts (scheduler).

A send answers with a ticket per message; whether the phone actually got it is only known from
the receipt, a few minutes later. Both say ``DeviceNotRegistered`` when the app was removed or
its token rotated, and that device is disabled for good — Expo asks senders to stop.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.push import expo
from yupay.modules.push.models import PushDevice, PushMessage

log = get_logger("yupay.push.delivery")

DEFAULT_LIMIT: Final = expo.SEND_BATCH
MAX_ATTEMPTS: Final = 6
BACKOFF_CAP_SECONDS: Final = 3600
#: A receipt is ready within ~15 minutes and kept by Expo for a day.
RECEIPT_AFTER: Final = timedelta(minutes=15)
RECEIPT_GIVE_UP: Final = timedelta(hours=24)
#: Ticket or receipt errors that will not get better by retrying.
_GONE: Final = "DeviceNotRegistered"
_RETRY: Final = frozenset({"MessageRateExceeded"})

Sender = Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]
ReceiptReader = Callable[[list[str]], Awaitable[dict[str, dict[str, Any]]]]


def backoff_seconds(attempts: int) -> int:
    """30 s, 1 min, 2 min … capped at an hour."""
    return int(min(30 * 2 ** max(attempts - 1, 0), BACKOFF_CAP_SECONDS))


def _error_of(ticket: dict[str, Any]) -> str:
    details = ticket.get("details")
    code = details.get("error") if isinstance(details, dict) else None
    return str(code or ticket.get("message") or "error")[:200]


async def _claim(db: AsyncSession, *, limit: int) -> list[PushMessage]:
    rows = await db.execute(
        select(PushMessage)
        .where(PushMessage.status == "pending", PushMessage.next_attempt_at <= now())
        .order_by(PushMessage.next_attempt_at, PushMessage.created_at, PushMessage.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows.scalars())


async def _disable(db: AsyncSession, device_id: str) -> None:
    device = await db.get(PushDevice, device_id)
    if device is not None and device.disabled_at is None:
        device.disabled_at = now()
        device.disabled_reason = "not_registered"
        log.info("push.device.not_registered", device_id=device_id)


def _retry(message: PushMessage, error: str, *, after: float | None = None) -> None:
    message.attempts += 1
    message.last_error = error[:200]
    if message.attempts >= MAX_ATTEMPTS:
        message.status = "failed"
        return
    wait = after if after is not None else backoff_seconds(message.attempts)
    message.next_attempt_at = now() + timedelta(seconds=min(wait, BACKOFF_CAP_SECONDS))


async def drain_pending_pushes(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    live: bool | None = None,
    sender: Sender | None = None,
) -> int:
    """Claim due messages and send them to Expo in one request; outside prod, skip them.

    Args:
        db: Session. The caller owns the transaction.
        limit: Messages to claim, at most one Expo request's worth.
        live: Overrides ``ENVIRONMENT=prod``; tests pass it, the worker does not.
        sender: Replaces :func:`expo.send` in tests.

    Returns:
        How many messages this batch claimed. ``0`` means the queue is dry.
    """
    if live is None:
        live = get_settings().environment == "prod"
    claimed = await _claim(db, limit=min(limit, expo.SEND_BATCH))
    if not claimed:
        return 0
    devices = {
        d.id: d
        for d in (
            await db.execute(
                select(PushDevice).where(PushDevice.id.in_({m.device_id for m in claimed}))
            )
        ).scalars()
    }
    sendable: list[tuple[PushMessage, PushDevice]] = []
    for message in claimed:
        device = devices.get(message.device_id)
        if not live or device is None or device.disabled_at is not None:
            message.status = "skipped"
        else:
            sendable.append((message, device))
    if sendable:
        await _send(db, sendable, sender or expo.send)
    await db.flush()
    return len(claimed)


async def _send(
    db: AsyncSession, batch: list[tuple[PushMessage, PushDevice]], sender: Sender
) -> None:
    payload = [
        {
            "to": device.token,
            "title": message.title,
            "body": message.body,
            "data": message.data,
            "sound": "default",
            "priority": "high",
            "channelId": "orders",
        }
        for message, device in batch
    ]
    try:
        tickets = await sender(payload)
    except expo.ExpoUnavailableError as exc:
        log.warning("push.send_unavailable", error=str(exc), messages=len(batch))
        for message, _ in batch:
            _retry(message, str(exc), after=exc.retry_after)
        return
    except expo.ExpoRejectedError as exc:
        log.exception("push.send_rejected", messages=len(batch))
        for message, _ in batch:
            message.status = "failed"
            message.last_error = str(exc)[:200]
        return
    sent_at = now()
    for (message, device), ticket in zip(batch, tickets, strict=True):
        if ticket.get("status") == "ok" and ticket.get("id"):
            message.status = "sent"
            message.ticket_id = str(ticket["id"])[:64]
            message.sent_at = sent_at
            message.attempts += 1
            continue
        error = _error_of(ticket)
        if error in _RETRY:
            _retry(message, error)
            continue
        message.status = "failed"
        message.attempts += 1
        message.last_error = error
        if error == _GONE:
            await _disable(db, device.id)
    log.info("push.sent", messages=len(batch))


async def check_receipts(
    db: AsyncSession, *, limit: int = expo.RECEIPTS_BATCH, reader: ReceiptReader | None = None
) -> int:
    """Read the receipts of messages sent a while ago; disable devices Expo says are gone.

    Returns:
        How many messages got a verdict (a receipt, or given up on after a day).
    """
    moment = now()
    rows = (
        await db.execute(
            select(PushMessage)
            .where(
                PushMessage.status == "sent",
                PushMessage.receipt_checked_at.is_(None),
                PushMessage.sent_at <= moment - RECEIPT_AFTER,
            )
            .order_by(PushMessage.sent_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    messages = [m for m in rows if m.ticket_id]
    if not messages:
        return 0
    try:
        found = await (reader or expo.receipts)([m.ticket_id for m in messages if m.ticket_id])
    except (expo.ExpoUnavailableError, expo.ExpoRejectedError) as exc:
        log.warning("push.receipts_unavailable", error=str(exc))
        return 0
    done = 0
    for message in messages:
        receipt = found.get(message.ticket_id or "")
        if receipt is None:
            if message.sent_at is not None and moment - message.sent_at >= RECEIPT_GIVE_UP:
                message.receipt_status = "expired"
                message.receipt_checked_at = moment
                done += 1
            continue
        message.receipt_checked_at = moment
        done += 1
        if receipt.get("status") == "ok":
            message.receipt_status = "ok"
            continue
        message.receipt_status = "error"
        message.last_error = _error_of(receipt)
        if message.last_error == _GONE:
            await _disable(db, message.device_id)
    await db.flush()
    log.info("push.receipts_checked", checked=done)
    return done
