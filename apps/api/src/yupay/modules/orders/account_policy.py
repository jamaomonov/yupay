"""Per-account purchase policy set by an operator (2026-10-11).

Two switches on a ``users`` row, both read by :func:`orders.risk.review_reason`
after payment:

* ``purchase_limit_usd`` — a **lifetime** cap. Every paid, not refunded catalog
  order of the account counts, plus guest orders placed under its email, the
  current one included. Once the total goes past the cap the order is held for
  review: one $31 order on a $30 cap, or the fourth $10 order after three.
* ``trusted_at`` — a trusted account skips every review rule (amount, windows,
  new buyer, geo, the purchase cap itself) and the pre-charge veto. Delivery is
  automatic whatever the amount.

The account behind an order is its ``user_id``, or for a guest the account whose
email the guest typed. Never raises: a failed read answers "no policy", and the
standard rules decide as they did before.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select

from yupay.core.logging import get_logger
from yupay.modules.orders.models import Order
from yupay.modules.users.models import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.orders.account_policy")

#: Order statuses that mean money was kept: a refunded or failed order does not
#: count against the cap. A held order stays ``paid``, so it counts.
SPENT_STATUSES = ("paid", "fulfilling", "fulfilled", "delivered", "partially_refunded")


@dataclass(frozen=True)
class AccountPolicy:
    """What the operator set on the account behind one order."""

    user_id: str | None = None
    email: str | None = None
    trusted: bool = False
    limit_usd: Decimal | None = None


NO_POLICY = AccountPolicy()


async def _account(db: AsyncSession, order: Order) -> User | None:
    if order.user_id is not None:
        return await db.get(User, order.user_id)
    if not order.guest_email:
        return None
    return (
        await db.execute(
            select(User).where(
                User.email == order.guest_email.strip().lower(), User.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def _spent_usd(db: AsyncSession, order: Order, policy: AccountPolicy) -> Decimal:
    """Paid catalog orders of the account, the current one included."""
    owned = [Order.user_id == policy.user_id]
    if policy.email:
        owned.append(and_(Order.user_id.is_(None), Order.guest_email == policy.email))
    others = await db.scalar(
        select(func.coalesce(func.sum(Order.total_usd), 0)).where(
            or_(*owned),
            Order.id != order.id,
            Order.purpose == "catalog",
            Order.status.in_(SPENT_STATUSES),
        )
    )
    return Decimal(others or 0) + order.total_usd


async def policy_for(db: AsyncSession, order: Order) -> AccountPolicy:
    """The policy of the account behind ``order``; :data:`NO_POLICY` when none applies."""
    if order.user_id is None and not order.guest_email:
        return NO_POLICY
    try:
        async with db.begin_nested():
            user = await _account(db, order)
    except Exception:
        log.exception("orders.account_policy.read_failed", order_id=order.id)
        return NO_POLICY
    if user is None:
        return NO_POLICY
    return AccountPolicy(
        user_id=user.id,
        email=user.email.lower() if user.email else None,
        trusted=user.trusted_at is not None,
        limit_usd=user.purchase_limit_usd,
    )


async def over_limit(db: AsyncSession, order: Order, policy: AccountPolicy) -> bool:
    """Whether this order takes the account past its lifetime cap.

    A failed read holds the order: the operator set a cap on purpose, so not
    knowing the total is a reason for a human to look, not to deliver.
    """
    if policy.limit_usd is None or policy.user_id is None:
        return False
    try:
        async with db.begin_nested():
            spent = await _spent_usd(db, order, policy)
    except Exception:
        log.exception("orders.account_policy.sum_failed", order_id=order.id)
        return True
    return spent > policy.limit_usd


__all__ = ["NO_POLICY", "SPENT_STATUSES", "AccountPolicy", "over_limit", "policy_for"]
