"""Admin HTTP routes for the ``users`` module.

Customer-facing user queries live in ``auth`` (``GET /auth/me``). This file is
admin-only — list, detail, role management.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.users import service as svc
from yupay.modules.users.models import User
from yupay.modules.users.schemas import (
    UserAdminListOut,
    UserAdminOut,
    UserRolesIn,
)

admin_router = APIRouter(
    prefix="/admin/users",
    tags=["admin:users"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "",
    response_model=UserAdminListOut,
    summary="List users with optional substring search",
)
async def admin_list_users(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> UserAdminListOut:
    """Paged user listing. ``search`` matches display_name / email / tg_username
    / tg_user_id (when the term is a digit)."""
    capped_limit = max(1, min(limit, 200))
    rows, total = await svc.list_users_admin(
        db, search=search, limit=capped_limit, offset=max(0, offset)
    )
    return UserAdminListOut(
        items=[UserAdminOut.model_validate(u) for u in rows],
        total=total,
    )


@admin_router.get(
    "/{user_id}",
    response_model=UserAdminOut,
    summary="User detail",
)
async def admin_get_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> UserAdminOut:
    return UserAdminOut.model_validate(await svc.get_user_admin(db, user_id))


@admin_router.patch(
    "/{user_id}/roles",
    response_model=UserAdminOut,
    summary="Replace a user's role list (empty list = demote to plain user)",
)
async def admin_set_user_roles(
    user_id: str,
    body: UserRolesIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> UserAdminOut:
    user = await svc.set_user_roles(db, user_id, roles=body.roles)
    return UserAdminOut.model_validate(user)
