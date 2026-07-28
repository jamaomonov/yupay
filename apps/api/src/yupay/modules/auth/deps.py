"""FastAPI dependencies that resolve the authenticated principal.

These are used by routers across modules to extract the current user / guest from the
``Authorization`` header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from yupay.core.config import get_settings
from yupay.core.db import get_session
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
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
    db: AsyncSession = Depends(get_session),  # noqa: B008
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


@dataclass(frozen=True)
class RequestActor:
    """Who is making a request: a logged-in user or an order-scoped guest."""

    user_id: str | None
    guest_email: str | None
    user: User | None


async def resolve_request_actor(request: Request, db: AsyncSession) -> RequestActor:
    """Bearer → user; ``Guest <jwt>`` + ``X-Guest-Email`` → guest (email_hash-checked).

    Mirrors the order-view auth so guest reviews inherit the same capability model.
    """
    auth = request.headers.get("Authorization")
    if not auth:
        raise UnauthorizedError("authorization required")
    scheme, _, token = auth.partition(" ")
    if scheme == "Bearer":
        user = await resolve_current_user(db, token)
        return RequestActor(user_id=user.id, guest_email=None, user=user)
    if scheme == "Guest":
        email = request.headers.get("X-Guest-Email")
        if not email:
            raise ValidationError("X-Guest-Email header required for guest actor")
        normalised = email.strip().lower()
        claims = authjwt.verify(token, expected_kind="guest")
        expected = email_hash(normalised, get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        return RequestActor(user_id=None, guest_email=normalised, user=None)
    raise UnauthorizedError("invalid authorization scheme")
