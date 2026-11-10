"""One mailbox, one account: the address Gmail actually delivers to.

``a+x@gmail.com``, ``a.b@gmail.com`` and ``ab@googlemail.com`` all land in
``ab@gmail.com``. Uniqueness on the raw string let one person open 152 accounts
on one inbox in an hour (prod, 2026-11-01) and turned the registration form
into a relay that floods that inbox with verification emails. Registration now
refuses an address whose mailbox already holds a live account.

The ``+tag`` is dropped for every domain (Outlook, Yandex, iCloud and Fastmail
deliver it too); dots are dropped only for Gmail, the one provider that ignores
them. The stored ``users.email`` is untouched — this is a lookup key, never a
rewrite of what the person typed.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import ColumnElement, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.users.models import SteamLink, TelegramLink, User

_GMAIL: Final[frozenset[str]] = frozenset({"gmail.com", "googlemail.com"})


def mailbox_key(email: str) -> str:
    """The inbox an address delivers to, lower-cased, e.g. ``ab@gmail.com``."""
    local, _, domain = email.strip().lower().rpartition("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        return f"{local.replace('.', '')}@gmail.com"
    return f"{local}@{domain}"


def _sql_mailbox_key() -> ColumnElement[str]:
    """:func:`mailbox_key` in SQL, over the stored ``users.email``."""
    lowered = func.lower(User.email)
    local = func.split_part(func.split_part(lowered, "@", 1), "+", 1)
    domain = func.split_part(lowered, "@", 2)
    gmail = domain.in_(tuple(_GMAIL))
    return case(
        (gmail, func.replace(local, ".", "") + "@gmail.com"),
        else_=local + "@" + domain,
    )


async def mailbox_taken(db: AsyncSession, email: str) -> bool:
    """Whether a live account already uses the mailbox ``email`` delivers to.

    A sequential scan of ``users``: a few thousand rows, once per registration,
    behind the per-IP guard. Give it an expression index if signups grow by
    orders of magnitude.
    """
    stmt = (
        select(User.id)
        .where(
            User.deleted_at.is_(None),
            User.email.is_not(None),
            _sql_mailbox_key() == mailbox_key(email),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


async def pending_password_account(db: AsyncSession, email: str) -> User | None:
    """The live, never-verified email/password account on this mailbox, if any.

    Only an account that is nothing *but* an unverified password: no Telegram
    or Steam sign-in behind it. Such an account cannot log in yet, so the
    password on it is just a claim by whoever typed the address — and
    ``register_user`` lets the next registration replace it rather than leave
    it for the owner's verify click to arm. Locked, so two registrations
    racing on one inbox settle in order.
    """
    stmt = (
        select(User)
        .where(
            User.deleted_at.is_(None),
            User.email.is_not(None),
            User.email_verified_at.is_(None),
            User.password_hash.is_not(None),
            _sql_mailbox_key() == mailbox_key(email),
            ~exists().where(TelegramLink.user_id == User.id),
            ~exists().where(SteamLink.user_id == User.id),
        )
        .limit(1)
        .with_for_update(of=User)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
