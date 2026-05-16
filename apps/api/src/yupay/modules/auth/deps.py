"""FastAPI dependencies that resolve the authenticated principal.

These are used by routers across modules to extract the current user / guest from the
``Authorization`` header.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import UnauthorizedError
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.service import current_user as resolve_current_user
from yupay.modules.users.models import User


def _extract_bearer(authorization: str | None, *, prefix: str = "Bearer") -> str:
    if not authorization:
        raise UnauthorizedError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if not token or scheme != prefix:
        raise UnauthorizedError("invalid Authorization scheme")
    return token.strip()


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session),  # noqa: B008
) -> User:
    """FastAPI dependency: resolve the authenticated user from a Bearer JWT."""
    token = _extract_bearer(authorization)
    return await resolve_current_user(db, token)


async def current_guest_claims(
    authorization: Annotated[str | None, Header()] = None,
) -> authjwt.Claims:
    """Decode a ``Guest <jwt>`` header. Does **not** touch the DB."""
    token = _extract_bearer(authorization, prefix="Guest")
    return authjwt.verify(token, expected_kind="guest")
