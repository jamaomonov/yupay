"""HTTP routes for ``broadcasts``: admin draft CRUD, FSM actions, and test-send.

Every handler is thin — parse the request, call ``broadcasts.service``, shape the
response. All business rules (FSM guards, body re-validation, audience sizing) live in
``service``/``sanitize``; nothing here duplicates them.
"""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.admin.api import require_admin
from yupay.modules.broadcasts import service as svc
from yupay.modules.broadcasts.schemas import (
    AudienceCountOut,
    BroadcastCreateIn,
    BroadcastListOut,
    BroadcastOut,
    BroadcastStatus,
    BroadcastUpdateIn,
    LocaleFilter,
    RecipientListOut,
    RecipientOut,
    RecipientStatus,
    ScheduleIn,
)
from yupay.modules.notifications.channels.telegram import send_broadcast_message
from yupay.modules.users.models import TelegramLink, User

admin_router = APIRouter(
    prefix="/admin/broadcasts",
    tags=["admin:broadcasts"],
    dependencies=[Depends(require_admin)],
)


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


# ---------- listing / creation ----------


@admin_router.get("", response_model=BroadcastListOut, summary="List broadcasts")
async def admin_list_broadcasts(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    status_filter: BroadcastStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> BroadcastListOut:
    rows, total = await svc.list_broadcasts(
        db,
        status_filter=status_filter,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )
    return BroadcastListOut(items=[BroadcastOut.model_validate(r) for r in rows], total=total)


@admin_router.post(
    "",
    response_model=BroadcastOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a broadcast draft",
)
async def admin_create_broadcast(
    body: BroadcastCreateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BroadcastOut:
    _require_idempotency_key(idempotency_key)
    broadcast = await svc.create_draft(db, actor_id=admin.id, data=body)
    return BroadcastOut.model_validate(broadcast)


# ---------- audience preview (must precede /{broadcast_id} to avoid shadowing) ----------


@admin_router.get(
    "/audience-count", response_model=AudienceCountOut, summary="Preview audience size"
)
async def admin_audience_count(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    locale: LocaleFilter | None = None,
) -> AudienceCountOut:
    count = await svc.audience_count(db, locale_filter=locale)
    return AudienceCountOut(count=count)


# ---------- single-broadcast CRUD ----------


@admin_router.get("/{broadcast_id}", response_model=BroadcastOut, summary="Get one broadcast")
async def admin_get_broadcast(
    broadcast_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> BroadcastOut:
    broadcast = await svc.get(db, broadcast_id=broadcast_id)
    return BroadcastOut.model_validate(broadcast)


@admin_router.patch("/{broadcast_id}", response_model=BroadcastOut, summary="Edit a draft")
async def admin_update_broadcast(
    broadcast_id: str,
    body: BroadcastUpdateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BroadcastOut:
    _require_idempotency_key(idempotency_key)
    broadcast = await svc.update_draft(db, broadcast_id=broadcast_id, data=body)
    return BroadcastOut.model_validate(broadcast)


@admin_router.delete(
    "/{broadcast_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft",
)
async def admin_delete_broadcast(
    broadcast_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> None:
    _require_idempotency_key(idempotency_key)
    await svc.delete_draft(db, broadcast_id=broadcast_id)


# ---------- FSM actions ----------


@admin_router.post(
    "/{broadcast_id}/test",
    summary="Send a test message to the calling admin's linked Telegram account",
)
async def admin_test_broadcast(
    broadcast_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> dict[str, bool]:
    """Send the current draft content to the calling admin, without touching FSM state."""
    _require_idempotency_key(idempotency_key)
    broadcast = await svc.get(db, broadcast_id=broadcast_id)
    link = (
        await db.execute(select(TelegramLink).where(TelegramLink.user_id == admin.id))
    ).scalar_one_or_none()
    if link is None:
        raise ValidationError("привяжите Telegram, чтобы получить тест")
    settings = get_settings()
    outcome = await send_broadcast_message(
        bot_token=settings.telegram_bot_token,
        chat_id=link.tg_user_id,
        body_html=broadcast.body_html,
        media_type=broadcast.media_type,
        # Test-send always uses the stored URL, never a captured file_id — a test
        # send may be the very first send for this broadcast, so no file_id exists yet.
        media_url_or_file_id=broadcast.media_url,
        disable_web_page_preview=broadcast.disable_web_page_preview,
    )
    return {"ok": outcome.ok}


@admin_router.post(
    "/{broadcast_id}/send",
    response_model=BroadcastOut,
    summary="Queue a broadcast for immediate dispatch",
)
async def admin_send_broadcast(
    broadcast_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BroadcastOut:
    _require_idempotency_key(idempotency_key)
    broadcast = await svc.mark_send_now(db, broadcast_id=broadcast_id)
    return BroadcastOut.model_validate(broadcast)


@admin_router.post(
    "/{broadcast_id}/schedule",
    response_model=BroadcastOut,
    summary="Queue a broadcast for future dispatch",
)
async def admin_schedule_broadcast(
    broadcast_id: str,
    body: ScheduleIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BroadcastOut:
    _require_idempotency_key(idempotency_key)
    # `service.schedule` compares against a tz-aware `now()`; a naive datetime would
    # raise an unhandled TypeError instead of a clean 422. Treat a naive input as UTC.
    scheduled_at = body.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    broadcast = await svc.schedule(db, broadcast_id=broadcast_id, scheduled_at=scheduled_at)
    return BroadcastOut.model_validate(broadcast)


@admin_router.post(
    "/{broadcast_id}/cancel",
    response_model=BroadcastOut,
    summary="Cancel a scheduled or in-flight broadcast",
)
async def admin_cancel_broadcast(
    broadcast_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BroadcastOut:
    _require_idempotency_key(idempotency_key)
    broadcast = await svc.cancel(db, broadcast_id=broadcast_id)
    return BroadcastOut.model_validate(broadcast)


# ---------- recipients ----------


@admin_router.get(
    "/{broadcast_id}/recipients",
    response_model=RecipientListOut,
    summary="List a broadcast's targeted recipients",
)
async def admin_list_recipients(
    broadcast_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    status: RecipientStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> RecipientListOut:
    rows, total = await svc.list_recipients(
        db,
        broadcast_id=broadcast_id,
        status_filter=status,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return RecipientListOut(items=[RecipientOut.model_validate(r) for r in rows], total=total)


__all__ = ["admin_router"]
