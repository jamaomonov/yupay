"""FastAPI dependencies for the partner panel.

Kept apart from ``routes`` so that ``partners``-side code can depend on it
without pulling a router in — the import cycle this module family has already
walked into once.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import UnauthorizedError
from yupay.modules.affiliate.models import AffiliatePartner
from yupay.modules.affiliate.partners import resolve_partner


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise UnauthorizedError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if not token or scheme != "Bearer":
        raise UnauthorizedError("invalid Authorization scheme")
    return token.strip()


async def current_partner(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session),  # noqa: B008
) -> AffiliatePartner:
    """Resolve the partner behind a ``Bearer`` partner access token.

    Every panel route depends on this and takes its partner id from the result,
    never from a request parameter. That is what keeps one partner out of
    another's earnings.
    """
    return await resolve_partner(db, _bearer(authorization))


__all__ = ["current_partner"]
