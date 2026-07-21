"""Broadcasts service: draft CRUD, the send/schedule/cancel FSM, and audience sizing.

FSM: ``draft`` and ``scheduled`` are the only editable states — an admin can revise the
body, re-target the audience, send immediately, (re-)schedule, or delete the draft from
either. Sending (immediate or scheduled) is a one-way door once the dispatch job picks it
up (``sending``); from there only ``cancel`` is legal, until the (later-task) dispatch job
settles the broadcast into ``sent``/``failed``. ``mark_send_now``/``schedule`` always
re-run ``sanitize.validate_body`` against the *stored* body — a body persisted by
``create_draft``/``update_draft`` is never assumed to already be valid, since neither of
those write paths validates it (see ``sanitize.validate_body``'s own docstring on the
save-time-vs-send-time split).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.broadcasts import sanitize
from yupay.modules.broadcasts.models import Broadcast, BroadcastRecipient
from yupay.modules.broadcasts.schemas import BroadcastCreateIn, BroadcastUpdateIn
from yupay.modules.users.models import TelegramLink, User

# Only these two statuses may still be edited, sent, or (re-)scheduled.
_EDITABLE_STATUSES = ("draft", "scheduled")
# A schedule must clear the dispatch job's own polling window; 5s is the floor.
_MIN_SCHEDULE_LEAD = timedelta(seconds=5)


async def create_draft(db: AsyncSession, *, actor_id: str, data: BroadcastCreateIn) -> Broadcast:
    """Create a new broadcast; always starts in ``draft`` (the column's server default)."""
    broadcast = Broadcast(
        id=new_id(),
        title=data.title,
        body_html=data.body_html,
        media_type=data.media_type,
        media_url=data.media_url,
        locale_filter=data.locale_filter,
        disable_web_page_preview=data.disable_web_page_preview,
        created_by=actor_id,
    )
    db.add(broadcast)
    await db.flush()
    return broadcast


async def get(db: AsyncSession, *, broadcast_id: str) -> Broadcast:
    """Fetch one broadcast by id.

    Raises:
        NotFoundError: if no broadcast with that id exists.
    """
    broadcast = (
        await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
    ).scalar_one_or_none()
    if broadcast is None:
        raise NotFoundError("broadcast not found")
    return broadcast


async def update_draft(
    db: AsyncSession, *, broadcast_id: str, data: BroadcastUpdateIn
) -> Broadcast:
    """Overwrite a draft's (or scheduled broadcast's) content.

    Editing a ``scheduled`` broadcast resets it to ``draft`` and clears
    ``scheduled_at`` — the admin must re-schedule explicitly after changing the content.

    Raises:
        ConflictError: if the broadcast is not currently ``draft`` or ``scheduled``.
    """
    broadcast = await get(db, broadcast_id=broadcast_id)
    if broadcast.status not in _EDITABLE_STATUSES:
        raise ConflictError("only a draft or scheduled broadcast can be edited")
    broadcast.title = data.title
    broadcast.body_html = data.body_html
    broadcast.media_type = data.media_type
    broadcast.media_url = data.media_url
    broadcast.locale_filter = data.locale_filter
    broadcast.disable_web_page_preview = data.disable_web_page_preview
    if broadcast.status == "scheduled":
        broadcast.status = "draft"
        broadcast.scheduled_at = None
    await db.flush()
    return broadcast


async def delete_draft(db: AsyncSession, *, broadcast_id: str) -> None:
    """Delete a broadcast that hasn't been scheduled or sent yet.

    Raises:
        ConflictError: if the broadcast is not currently ``draft``.
    """
    broadcast = await get(db, broadcast_id=broadcast_id)
    if broadcast.status != "draft":
        raise ConflictError("only a draft broadcast can be deleted")
    await db.delete(broadcast)
    await db.flush()


async def list_broadcasts(
    db: AsyncSession,
    *,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Broadcast], int]:
    """Paged admin listing, newest ``created_at`` first. Returns ``(rows, total)``."""
    base = select(Broadcast)
    count_stmt = select(func.count()).select_from(Broadcast)
    if status_filter is not None:
        base = base.where(Broadcast.status == status_filter)
        count_stmt = count_stmt.where(Broadcast.status == status_filter)
    rows = list(
        (await db.execute(base.order_by(Broadcast.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


async def audience_count(db: AsyncSession, *, locale_filter: str | None) -> int:
    """Count Telegram-linked users eligible for a broadcast.

    Excludes anyone whose bot chat is known-blocked (``bot_blocked_at IS NOT NULL``);
    optionally narrows to a single ``users.locale``.
    """
    stmt = (
        select(func.count())
        .select_from(TelegramLink)
        .join(User, User.id == TelegramLink.user_id)
        .where(TelegramLink.bot_blocked_at.is_(None))
    )
    if locale_filter is not None:
        stmt = stmt.where(User.locale == locale_filter)
    return int((await db.execute(stmt)).scalar_one() or 0)


def _validate_sendable(broadcast: Broadcast) -> None:
    """Re-validate a broadcast's stored body just before it can be sent/scheduled.

    Raises:
        ValidationError: if there's no media and the body is empty/whitespace-only,
            or if the body fails ``sanitize.validate_body`` (disallowed tag/attr,
            unbalanced markup, or over the visible-length ceiling).
    """
    has_media = broadcast.media_type != "none"
    if not has_media and broadcast.body_html.strip() == "":
        raise ValidationError("сообщение пустое")
    sanitize.validate_body(broadcast.body_html, has_media=has_media)


async def mark_send_now(db: AsyncSession, *, broadcast_id: str) -> Broadcast:
    """Queue a broadcast for immediate dispatch.

    Raises:
        ConflictError: if the broadcast is not currently ``draft`` or ``scheduled``.
        ValidationError: if the stored body fails re-validation (see ``_validate_sendable``).
    """
    broadcast = await get(db, broadcast_id=broadcast_id)
    if broadcast.status not in _EDITABLE_STATUSES:
        raise ConflictError("only a draft or scheduled broadcast can be sent")
    _validate_sendable(broadcast)
    broadcast.status = "sending"
    broadcast.scheduled_at = None
    await db.flush()
    return broadcast


async def schedule(db: AsyncSession, *, broadcast_id: str, scheduled_at: datetime) -> Broadcast:
    """Queue a broadcast for future dispatch at ``scheduled_at``.

    Raises:
        ConflictError: if the broadcast is not currently ``draft`` or ``scheduled``.
        ValidationError: if the stored body fails re-validation, or if ``scheduled_at``
            is not at least :data:`_MIN_SCHEDULE_LEAD` in the future.
    """
    broadcast = await get(db, broadcast_id=broadcast_id)
    if broadcast.status not in _EDITABLE_STATUSES:
        raise ConflictError("only a draft or scheduled broadcast can be scheduled")
    _validate_sendable(broadcast)
    if scheduled_at <= now() + _MIN_SCHEDULE_LEAD:
        raise ValidationError("scheduled_at must be at least 5 seconds in the future")
    broadcast.status = "scheduled"
    broadcast.scheduled_at = scheduled_at
    await db.flush()
    return broadcast


async def cancel(db: AsyncSession, *, broadcast_id: str) -> Broadcast:
    """Cancel a broadcast that's queued or already dispatching.

    Raises:
        ConflictError: if the broadcast is not currently ``scheduled`` or ``sending``.
    """
    broadcast = await get(db, broadcast_id=broadcast_id)
    if broadcast.status not in ("scheduled", "sending"):
        raise ConflictError("only a scheduled or sending broadcast can be canceled")
    broadcast.status = "canceled"
    broadcast.finished_at = now()
    await db.flush()
    return broadcast


async def list_recipients(
    db: AsyncSession,
    *,
    broadcast_id: str,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[BroadcastRecipient], int]:
    """Paged listing of one broadcast's recipient rows. Returns ``(rows, total)``."""
    base = select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast_id)
    count_stmt = (
        select(func.count())
        .select_from(BroadcastRecipient)
        .where(BroadcastRecipient.broadcast_id == broadcast_id)
    )
    if status_filter is not None:
        base = base.where(BroadcastRecipient.status == status_filter)
        count_stmt = count_stmt.where(BroadcastRecipient.status == status_filter)
    rows = list(
        (
            await db.execute(
                base.order_by(BroadcastRecipient.created_at.asc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


__all__ = [
    "audience_count",
    "cancel",
    "create_draft",
    "delete_draft",
    "get",
    "list_broadcasts",
    "list_recipients",
    "mark_send_now",
    "schedule",
    "update_draft",
]
