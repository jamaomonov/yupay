"""User upsert / lookup service.

All cross-module callers should import from :mod:`yupay.modules.users.api`, never from
here directly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.auth.telegram import TelegramUser
from yupay.modules.users.models import TelegramLink, User


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    """Return the user row or ``None`` if not found / soft-deleted."""
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_telegram_id(session: AsyncSession, tg_user_id: int) -> User | None:
    """Look up the user joined to a Telegram identity, if any."""
    stmt = (
        select(User)
        .join(TelegramLink, TelegramLink.user_id == User.id)
        .where(TelegramLink.tg_user_id == tg_user_id, User.deleted_at.is_(None))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_user_by_telegram(
    session: AsyncSession,
    tg_user: TelegramUser,
    *,
    locale_hint: str | None = None,
) -> User:
    """Find-or-create a user from a verified Telegram identity.

    On first sight we create both the ``users`` row and the ``telegram_links`` row.
    On subsequent visits we touch ``last_seen_at`` and refresh mutable Telegram fields.
    The ``locale_hint`` is only applied at creation time — we don't override an existing
    user's locale choice.
    """
    existing = await get_user_by_telegram_id(session, tg_user.id)
    if existing is not None:
        link = existing.telegram_link
        if link is not None:
            link.tg_username = tg_user.username
            link.first_name = tg_user.first_name
            link.last_name = tg_user.last_name
            link.language_code = tg_user.language_code
            link.is_premium = tg_user.is_premium
            link.last_seen_at = now()
        if tg_user.photo_url and not existing.photo_url:
            existing.photo_url = tg_user.photo_url
        existing.updated_at = now()
        await session.flush()
        return existing

    locale = (locale_hint or tg_user.language_code or "ru").split("-")[0][:8] or "ru"
    user = User(
        id=new_id(),
        email=None,
        locale=locale,
        display_name=(tg_user.first_name or tg_user.username),
        photo_url=tg_user.photo_url,
    )
    link = TelegramLink(
        id=new_id(),
        user_id=user.id,
        tg_user_id=tg_user.id,
        tg_username=tg_user.username,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        language_code=tg_user.language_code,
        is_premium=tg_user.is_premium,
    )
    session.add(user)
    session.add(link)
    await session.flush()
    return user


__all__ = [
    "get_user_by_id",
    "get_user_by_telegram_id",
    "upsert_user_by_telegram",
]
