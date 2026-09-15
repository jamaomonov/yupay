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
from yupay.modules.merchants.models import Merchant, MerchantUser


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


#: The two annotations every cabinet route repeats. Here rather than in one
#: router, because there are two of them now and a second copy is how they
#: come to mean different things.
Db = Annotated[AsyncSession, Depends(db_session)]
CurrentUser = Annotated[MerchantUser, Depends(current_merchant_user)]


async def merchant_of(db: AsyncSession, user: MerchantUser) -> Merchant:
    """The company behind the signed-in operator.

    :func:`current_merchant_user` has already proved it exists and is active,
    so this is a load and not a check — but it is loaded **fresh on every
    request** rather than carried in the token, so a freeze takes effect on
    the next call instead of when a JWT happens to expire.
    """
    merchant = await db.get(Merchant, user.merchant_id)
    assert merchant is not None, "resolve_user proved this row exists"
    return merchant


__all__ = ["CurrentUser", "Db", "current_merchant_user", "merchant_of"]
