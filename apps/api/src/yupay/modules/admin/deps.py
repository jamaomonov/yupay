"""FastAPI dependencies for admin endpoints.

See ADR-0010 for the role model. Admin gates resolve the current user via the
``auth`` module and then check membership in ``users.roles``. Revocation is
real-time — the next request after a ``roles`` update reflects the change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from yupay.core.config import get_settings
from yupay.core.errors import ForbiddenError, UnauthorizedError
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.deps import current_user
from yupay.modules.users.models import User


def has_role(user: User, role: str) -> bool:
    """Return ``True`` if ``user`` carries ``role`` (case-sensitive)."""
    return role in (user.roles or [])


async def require_admin(
    user: Annotated[User, Depends(current_user)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """FastAPI dependency: 200 if the current user is an admin, 403 otherwise.

    A non-admin Bearer token deliberately returns **403 Forbidden**, not 401, so the
    admin SPA can distinguish "not logged in" from "logged in but not allowed".

    The role is not enough on its own (audit 2026-11-10): the token must also
    come from an admin-panel session (``adm``, minted only by the admin login
    and ``/auth/admin/refresh``). Before, an admin's mini-app or storefront
    session was an admin session too, held in places the admin panel's
    defences never reached. A token without it answers **401**, so the SPA
    sends the operator back to its login rather than showing «no rights».
    """
    settings = get_settings()
    if settings.admin_session_required or not settings.is_test:
        # ``current_user`` above has already verified this token and resolved
        # its session; this reads one more claim off it.
        _, _, token = (authorization or "").partition(" ")
        if not authjwt.verify(token.strip(), expected_kind="access").adm:
            raise UnauthorizedError("admin session required — sign in to the admin panel")
    if not has_role(user, "admin"):
        raise ForbiddenError("admin role required")
    return user


__all__ = ["has_role", "require_admin"]
