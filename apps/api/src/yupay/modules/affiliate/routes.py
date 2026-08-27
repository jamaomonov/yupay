"""HTTP routes for ``affiliate``: the buyer-facing code preview.

Deliberately **not** re-exported from ``affiliate.api``. That facade is
imported by ``payments.service`` and ``orders.service``, and a router imported
from either of those closes a cycle back through the v1 route stack — the same
cycle that broke the first test written against this module. ``api/v1`` imports
this file directly instead.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.affiliate.discount import (
    ResolvedDiscount,
    discount_amount,
    resolve_code,
)
from yupay.modules.affiliate.schemas import PreviewIn, PreviewOut
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.orders.schemas import OrderCreate
from yupay.modules.orders.service import quote_cart
from yupay.modules.users.models import User

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


@router.post(
    "/preview",
    response_model=PreviewOut,
    summary="What a partner code would do to this cart",
)
async def preview(
    body: PreviewIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> PreviewOut:
    """Price the cart, then say whether the code applies to it.

    Signed-in only, because a partner code binds a buyer to a partner and a
    guest has nothing durable to bind. That also gives the throttle a subject:
    the two-axis guard keys on the buyer, so one account cannot grind through
    the code space from a rotating address.

    The amounts are for display only. ``create_order`` resolves the code again
    and prices the order itself, so nothing here can be spent.
    """
    # This endpoint answers "is this string a usable promo code", which is a
    # guessing surface by construction. The codes are short and advertised, so
    # they cannot be made unguessable — the throttle is the whole defence.
    await guard_ip(request, bucket="affiliate-preview", subject=user.id)

    quote = await quote_cart(db, OrderCreate(currency=body.currency, items=body.items))

    resolved = await resolve_code(db, code=body.code, user_id=user.id, purpose="catalog")
    if not isinstance(resolved, ResolvedDiscount):
        return PreviewOut(
            applicable=False,
            reason=resolved,
            currency=quote.currency,
            total_before=quote.total_charged,
            total_after=quote.total_charged,
            discount=Decimal("0"),
        )

    discount = discount_amount(quote.total_charged, resolved.percent, quote.currency)
    return PreviewOut(
        applicable=True,
        code=resolved.code,
        percent=resolved.percent,
        currency=quote.currency,
        total_before=quote.total_charged,
        total_after=quote.total_charged - discount,
        discount=discount,
    )


__all__ = ["router"]
