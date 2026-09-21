"""Who can sign into a reseller's cabinet — the admin's read of it.

Support's first question on "I cannot get in" is not about passwords. It is
whether the address was ever confirmed, and whether that person has ever
signed in at all: an unconfirmed operator and one who signed in last month
are two different conversations, and until this module there was no screen
that told them apart.

Read-only, and deliberately narrow. Nothing here returns a password hash, a
session token or anything else that could be replayed — the shape is
:class:`MerchantUserOut`, which has no field for them.

``last_login_at`` is derived rather than stored. ``merchant_sessions`` gets a
row per sign-in, so the newest ``created_at`` under a person IS their last
login; a dedicated column would be a second source of the same fact, and the
one that drifts. It is computed as a grouped subquery joined once, not a
query per operator — a merchant has few operators today and that is not a
reason to write the shape that stops being true.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from yupay.modules.merchants.models import MerchantSession, MerchantUser
from yupay.modules.merchants.schemas import MerchantUserListOut, MerchantUserOut
from yupay.modules.merchants.service import get_merchant

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_operators(db: AsyncSession, *, merchant_id: str) -> MerchantUserListOut:
    """Every person who can sign into this merchant's cabinet, oldest first.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose operators to list. Must exist.

    Returns:
        The rows, each with a derived ``last_login_at``.

    Raises:
        NotFoundError: If no merchant with that id exists — an empty list for
            a typo'd id must be a 404, never a plausible-looking ``[]``.
    """
    await get_merchant(db, merchant_id)
    # One grouped subquery, joined once. A per-row "newest session" lookup
    # would be the N+1 this codebase's list endpoints all have a test against.
    last_login = (
        select(
            MerchantSession.merchant_user_id.label("user_id"),
            func.max(MerchantSession.created_at).label("at"),
        )
        .group_by(MerchantSession.merchant_user_id)
        .subquery()
    )
    stmt = (
        select(MerchantUser, last_login.c.at)
        .outerjoin(last_login, last_login.c.user_id == MerchantUser.id)
        .where(MerchantUser.merchant_id == merchant_id)
        # Oldest first: the first operator is whoever registered the account,
        # and on a two-person account that is the one support is asking about.
        .order_by(MerchantUser.created_at.asc(), MerchantUser.id.asc())
    )
    rows = list((await db.execute(stmt)).all())
    # Built field by field rather than `model_validate(user)`: `last_login_at`
    # comes from the join, not from the ORM object, so there is nothing on
    # `user` for `from_attributes` to read it off.
    return MerchantUserListOut(
        items=[
            MerchantUserOut(
                id=user.id,
                email=user.email,
                email_confirmed_at=user.email_confirmed_at,
                last_login_at=last_at,
                timezone=user.timezone,
                offer_version=user.offer_version,
                offer_accepted_at=user.offer_accepted_at,
                created_at=user.created_at,
            )
            for user, last_at in rows
        ]
    )


__all__ = ["list_operators"]
