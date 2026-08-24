"""HTTP routes for the ``users`` module.

Customer-facing reads still live in ``auth`` (``GET /auth/me`` — same JWT
gate). This file exposes:

* ``/users/me`` — customer ``PATCH`` for editable preferences (display
  currency, locale). Adding more profile fields here later is a pure
  additive change.
* ``/admin/users`` — admin CRUD for the user directory.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.users import service as svc
from yupay.modules.users.models import User
from yupay.modules.users.schemas import (
    BanUserIn,
    UpdateMeIn,
    UserAdminListOut,
    UserAdminOut,
    UserOut,
    UserRolesIn,
)

router = APIRouter(prefix="/users", tags=["users"])
admin_router = APIRouter(
    prefix="/admin/users",
    tags=["admin:users"],
    dependencies=[Depends(require_admin)],
)


@router.patch(
    "/me",
    response_model=UserOut,
    summary="Update the authenticated user's preferences",
)
async def update_me_route(
    body: UpdateMeIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> UserOut:
    """Partial update — only the fields actually sent are applied."""
    updated = await svc.update_me(
        db,
        user.id,
        display_currency=body.display_currency,
        locale=body.locale,
        delivery_email=body.delivery_email,
    )
    return UserOut.model_validate(updated)


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


@admin_router.post(
    "/{user_id}/ban",
    response_model=UserAdminOut,
    summary="Suspend an account",
)
async def admin_ban_user(
    user_id: str,
    body: BanUserIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> UserAdminOut:
    """Ban a customer.

    Takes effect on the account's next request: ``auth.current_user`` re-reads
    the flag every time, so an access token minted seconds ago stops working.
    Guest checkout under the same email is refused too — see ADR-0045 for what
    a ban does and, just as importantly, what it does not do.
    """
    user = await svc.ban_user(db, user_id, by_admin_id=admin.id, reason=body.reason)
    return UserAdminOut.model_validate(user)


@admin_router.post(
    "/{user_id}/unban",
    response_model=UserAdminOut,
    summary="Lift a suspension",
)
async def admin_unban_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> UserAdminOut:
    """Restore access. Idempotent on an account that is not banned."""
    user = await svc.unban_user(db, user_id)
    return UserAdminOut.model_validate(user)
