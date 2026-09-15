"""FastAPI dependencies for the merchant cabinet.

Kept apart from the routes for the reason ``affiliate.deps`` states: service
code needs the dependency without pulling a router in, and this module family
has walked into that cycle before.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import UnauthorizedError
from yupay.modules.merchants.cabinet_auth import resolve_user
from yupay.modules.merchants.models import MerchantUser


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise UnauthorizedError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if not token or scheme != "Bearer":
        raise UnauthorizedError("invalid Authorization scheme")
    return token.strip()


async def current_merchant_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session),  # noqa: B008
) -> MerchantUser:
    """Resolve the operator behind a ``Bearer`` cabinet access token.

    Every cabinet route depends on this and takes the merchant id from
    ``user.merchant_id``, **never** from a request parameter. That is the one
    rule keeping one reseller out of another's orders, deposit and keys — the
    same rule ``current_partner`` enforces one actor over.
    """
    return await resolve_user(db, _bearer(authorization))


__all__ = ["current_merchant_user"]
