"""User upsert / lookup service.

All cross-module callers should import from :mod:`yupay.modules.users.api`, never from
here directly.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import NotFoundError
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


async def list_users_admin(
    session: AsyncSession,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    """Admin listing with optional substring search across display_name, email,
    Telegram username and Telegram user id."""
    base = select(User).options(selectinload(User.telegram_link))
    count_stmt = select(func.count()).select_from(User)
    if search and search.strip():
        q = f"%{search.strip()}%"
        as_int = None
        if search.strip().isdigit():
            try:
                as_int = int(search.strip())
            except ValueError:
                as_int = None
        join_clauses = [
            User.display_name.ilike(q),
            User.email.ilike(q),
        ]
        # Telegram-side filters need a join. We do an outer join so a user
        # without a TG link can still match by display_name/email above.
        base = base.outerjoin(TelegramLink, TelegramLink.user_id == User.id)
        count_stmt = count_stmt.outerjoin(TelegramLink, TelegramLink.user_id == User.id)
        join_clauses.append(TelegramLink.tg_username.ilike(q))
        if as_int is not None:
            join_clauses.append(TelegramLink.tg_user_id == as_int)
        base = base.where(or_(*join_clauses))
        count_stmt = count_stmt.where(or_(*join_clauses))

    items = list(
        (await session.execute(base.order_by(User.created_at.desc()).limit(limit).offset(offset)))
        .unique()
        .scalars()
        .all()
    )
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    return items, total


async def get_user_admin(session: AsyncSession, user_id: str) -> User:
    """Load a user with the Telegram link eager-loaded; 404 if missing."""
    stmt = select(User).options(selectinload(User.telegram_link)).where(User.id == user_id)
    row = (await session.execute(stmt)).unique().scalar_one_or_none()
    if row is None:
        raise NotFoundError("user not found")
    return row


# Roles we accept on a user record. Anything else is rejected at the route layer.
_ALLOWED_ROLES = frozenset({"admin"})


async def set_user_roles(session: AsyncSession, user_id: str, *, roles: list[str]) -> User:
    """Replace the user's roles list. Unknown roles raise NotFoundError-friendly
    error via core.errors. Empty list means "demote to plain user"."""
    user = await get_user_admin(session, user_id)
    cleaned: list[str] = []
    seen: set[str] = set()
    for r in roles:
        r2 = r.strip().lower()
        if not r2 or r2 in seen:
            continue
        if r2 not in _ALLOWED_ROLES:
            from yupay.core.errors import ValidationError

            raise ValidationError(f"unknown role: {r2}", allowed=sorted(_ALLOWED_ROLES))
        seen.add(r2)
        cleaned.append(r2)
    user.roles = cleaned
    user.updated_at = now()
    await session.flush()
    return user


# Mirror of the Pydantic Literal in ``schemas.UpdateMeIn``. Defining it here
# too keeps the service layer self-contained for cross-module callers that
# import ``users.api`` without pulling Pydantic in.
_ALLOWED_DISPLAY_CURRENCIES = frozenset({"USD", "UZS", "RUB", "USDT"})


async def update_me(
    session: AsyncSession,
    user_id: str,
    *,
    display_currency: str | None = None,
    locale: str | None = None,
) -> User:
    """Patch the authenticated user's preferences.

    Only fields whose value is not ``None`` are touched, so callers can send
    partial bodies. Unknown currencies are rejected as a 400 — they would
    otherwise break the storefront's FX lookup and silently degrade prices.
    """
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("user not found")
    if display_currency is not None:
        currency = display_currency.strip().upper()
        if currency not in _ALLOWED_DISPLAY_CURRENCIES:
            from yupay.core.errors import ValidationError

            raise ValidationError(
                f"unsupported display currency: {currency!r}",
                allowed=sorted(_ALLOWED_DISPLAY_CURRENCIES),
            )
        user.display_currency = currency
    if locale is not None:
        cleaned = locale.strip().split("-")[0][:8]
        if cleaned:
            user.locale = cleaned
    user.updated_at = now()
    await session.flush()
    return user


__all__ = [
    "get_user_admin",
    "get_user_by_id",
    "get_user_by_telegram_id",
    "list_users_admin",
    "set_user_roles",
    "update_me",
    "upsert_user_by_telegram",
]
