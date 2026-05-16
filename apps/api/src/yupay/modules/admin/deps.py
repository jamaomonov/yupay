"""FastAPI dependencies for admin endpoints.

See ADR-0010 for the role model. Admin gates resolve the current user via the
``auth`` module and then check membership in ``users.roles``. Revocation is
real-time — the next request after a ``roles`` update reflects the change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from yupay.core.errors import ForbiddenError
from yupay.modules.auth.deps import current_user
from yupay.modules.users.models import User


def has_role(user: User, role: str) -> bool:
    """Return ``True`` if ``user`` carries ``role`` (case-sensitive)."""
    return role in (user.roles or [])


async def require_admin(
    user: Annotated[User, Depends(current_user)],
) -> User:
    """FastAPI dependency: 200 if the current user is an admin, 403 otherwise.

    A non-admin Bearer token deliberately returns **403 Forbidden**, not 401, so the
    admin SPA can distinguish "not logged in" from "logged in but not allowed".
    """
    if not has_role(user, "admin"):
        raise ForbiddenError("admin role required")
    return user


__all__ = ["has_role", "require_admin"]
