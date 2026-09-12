"""Admin CRUD and lifecycle actions for editorial posts."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.admin.api import require_admin
from yupay.modules.blog import admin_service as svc
from yupay.modules.blog.admin_schemas import (
    AdminPostListOut,
    AdminPostOut,
    PostCreate,
    PostUpdate,
    ScheduleIn,
)
from yupay.modules.blog.schemas import PostStatus
from yupay.modules.users.models import User

router = APIRouter(
    prefix="/admin/blog",
    tags=["admin:blog"],
    dependencies=[Depends(require_admin)],
)


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


@router.get("/posts", response_model=AdminPostListOut, summary="List posts")
async def admin_list_posts(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    status_filter: PostStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AdminPostListOut:
    rows, total = await svc.list_posts(db, status_filter=status_filter, limit=limit, offset=offset)
    return AdminPostListOut(items=[svc.serialize_admin(row) for row in rows], total=total)


@router.post(
    "/posts",
    response_model=AdminPostOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft",
)
async def admin_create_post(
    body: PostCreate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminPostOut:
    _require_idempotency_key(idempotency_key)
    post = await svc.create_post(db, body)
    return svc.serialize_admin(post)


@router.get("/posts/{post_id}", response_model=AdminPostOut, summary="Get one post")
async def admin_get_post(
    post_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminPostOut:
    return svc.serialize_admin(await svc.get_post(db, post_id))


@router.patch("/posts/{post_id}", response_model=AdminPostOut, summary="Edit a post")
async def admin_update_post(
    post_id: str,
    body: PostUpdate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminPostOut:
    _require_idempotency_key(idempotency_key)
    return svc.serialize_admin(await svc.update_post(db, post_id, body))


@router.post("/posts/{post_id}/publish", response_model=AdminPostOut, summary="Publish")
async def admin_publish_post(
    post_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminPostOut:
    _require_idempotency_key(idempotency_key)
    return svc.serialize_admin(await svc.publish_post(db, post_id))


@router.post("/posts/{post_id}/archive", response_model=AdminPostOut, summary="Archive")
async def admin_archive_post(
    post_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminPostOut:
    _require_idempotency_key(idempotency_key)
    return svc.serialize_admin(await svc.archive_post(db, post_id))


@router.post("/posts/{post_id}/schedule", response_model=AdminPostOut, summary="Schedule")
async def admin_schedule_post(
    post_id: str,
    body: ScheduleIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminPostOut:
    _require_idempotency_key(idempotency_key)
    when = body.scheduled_for
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return svc.serialize_admin(await svc.schedule_post(db, post_id, when))
