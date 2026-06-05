"""Auth business logic.

Wraps :mod:`yupay.modules.auth.jwt`, :mod:`yupay.modules.auth.telegram`, and the
``users`` module into the five flows exposed by the HTTP layer:

- ``telegram_init_data_login`` (Mini App)
- ``telegram_widget_login`` (public web)
- ``guest_checkout`` (email-only checkout)
- ``refresh_session``
- ``logout``
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ConflictError, NotFoundError, UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth import telegram as tg
from yupay.modules.auth.models import AuthSession
from yupay.modules.auth.security import (
    email_hash,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import verify_email_email
from yupay.modules.users.models import User
from yupay.modules.users.service import (
    get_user_by_id,
    upsert_user_by_telegram,
)


@dataclass(frozen=True)
class SessionTokens:
    """Tuple of access + opaque refresh + their TTLs (seconds)."""

    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int
    user: User


@dataclass(frozen=True)
class GuestToken:
    """Result of a guest checkout."""

    access_token: str
    expires_in: int


async def _open_session(
    db: AsyncSession,
    *,
    user: User,
    settings: Settings,
    ip_hash: str | None = None,
    ua_hash: str | None = None,
) -> SessionTokens:
    """Create a fresh ``auth_sessions`` row and mint matching access + refresh."""
    refresh = new_refresh_token()
    session_id = new_id()
    session = AuthSession(
        id=session_id,
        user_id=user.id,
        kind="user",
        refresh_token_hash=hash_token(refresh),
        expires_at=now() + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
        ip_hash=ip_hash,
        ua_hash=ua_hash,
    )
    db.add(session)
    await db.flush()

    link = await user.awaitable_attrs.telegram_link
    tg_id = link.tg_user_id if link is not None else None
    e_hash = email_hash(user.email, settings.auth_email_pepper) if user.email else None
    access = authjwt.mint_access(
        sub=user.id,
        sid=session_id,
        tg_id=tg_id,
        email_hash=e_hash,
        settings=settings,
    )
    return SessionTokens(
        access_token=access,
        refresh_token=refresh,
        access_expires_in=settings.jwt_access_ttl_seconds,
        refresh_expires_in=settings.jwt_refresh_ttl_seconds,
        user=user,
    )


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    locale: str = "ru",
    settings: Settings | None = None,
    verify_link_base: str | None = None,
) -> SessionTokens:
    """Create an email/password user, open a session, and send a verify email.

    Args:
        db: Async session.
        email: New account email (uniqueness enforced by ``uq_users_email_alive``).
        password: Plaintext password (hashed with argon2id).
        locale: Preferred locale for the account.
        settings: Optional settings override.
        verify_link_base: Absolute URL prefix for the verification link, e.g.
            ``https://yupay.uz/ru``. When ``None`` no email is sent (dev).

    Returns:
        Freshly minted session tokens for immediate login.

    Raises:
        ConflictError: When the email already belongs to a live account.
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    user = User(
        id=new_id(),
        email=normalised,
        locale=locale,
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # The request-scoped session (``get_session``) rolls back on any raised
        # exception, so no explicit rollback is needed here.
        raise ConflictError("email already registered") from exc

    if verify_link_base:
        token = authjwt.mint_email_verify(sub=user.id, settings=s)
        link = f"{verify_link_base.rstrip('/')}/auth/verify?token={token}"
        content = verify_email_email(link=link)
        with contextlib.suppress(EmailSendError):
            # non-blocking: account is usable; user can re-request verification
            await send_email(
                to=normalised,
                subject=content.subject,
                html=content.html,
                text=content.text,
            )

    return await _open_session(db, user=user, settings=s)


async def login_password(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings | None = None,
) -> SessionTokens:
    """Authenticate an email/password user and open a session.

    Raises:
        UnauthorizedError: On unknown email, Telegram-only account (no password),
            or wrong password — all surfaced identically to avoid enumeration.
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    stmt = select(User).where(
        User.email == normalised,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise UnauthorizedError("invalid email or password")
    return await _open_session(db, user=user, settings=s)


async def telegram_init_data_login(
    db: AsyncSession,
    init_data: str,
    *,
    settings: Settings | None = None,
) -> SessionTokens:
    """Verify Mini App ``initData`` and open a session."""
    s = settings or get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    verified = tg.verify_init_data(
        init_data,
        bot_token=s.telegram_bot_token,
        max_age_seconds=s.telegram_init_data_ttl_seconds,
    )
    user = await upsert_user_by_telegram(db, verified.user)
    return await _open_session(db, user=user, settings=s)


async def telegram_widget_login(
    db: AsyncSession,
    payload: dict[str, str | int | bool],
    *,
    settings: Settings | None = None,
) -> SessionTokens:
    """Verify a Login Widget payload and open a session."""
    s = settings or get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    verified = tg.verify_login_widget(
        payload,
        bot_token=s.telegram_bot_token,
        max_age_seconds=s.telegram_init_data_ttl_seconds,
    )
    user = await upsert_user_by_telegram(db, verified.user)
    return await _open_session(db, user=user, settings=s)


async def guest_checkout(
    db: AsyncSession,
    email: str,
    *,
    settings: Settings | None = None,
) -> GuestToken:
    """Mint a short-lived guest token bound to an email.

    Persists an ``auth_sessions(kind='guest')`` row for audit, but the token itself is a
    standalone JWT (no refresh, no DB lookup needed on subsequent calls).
    """
    s = settings or get_settings()
    if not s.auth_email_pepper:
        raise RuntimeError("AUTH_EMAIL_PEPPER is not configured")

    normalised = email.strip().lower()
    e_hash = email_hash(normalised, s.auth_email_pepper)
    session = AuthSession(
        id=new_id(),
        user_id=None,
        kind="guest",
        refresh_token_hash=None,
        guest_email=normalised,
        expires_at=now() + timedelta(seconds=s.jwt_guest_ttl_seconds),
    )
    db.add(session)
    await db.flush()

    token = authjwt.mint_guest(email_hash=e_hash, settings=s)
    return GuestToken(access_token=token, expires_in=s.jwt_guest_ttl_seconds)


async def refresh_session(
    db: AsyncSession,
    refresh_token: str,
    *,
    settings: Settings | None = None,
) -> SessionTokens:
    """Rotate a refresh token: revoke the old row, mint new access + refresh.

    Implements the reuse-detection trip-wire from ADR-0007: presenting a refresh whose
    row is already ``revoked_at`` revokes **every** active session for the user.
    """
    s = settings or get_settings()
    token_hash = hash_token(refresh_token)

    stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    session_row = (await db.execute(stmt)).scalar_one_or_none()
    if session_row is None:
        raise UnauthorizedError("invalid refresh token")

    if session_row.revoked_at is not None:
        # Reuse detected — burn down the user's other sessions to limit blast radius.
        if session_row.user_id is not None:
            await _revoke_all_for_user(db, session_row.user_id)
        raise UnauthorizedError("refresh token reuse detected")

    if session_row.expires_at <= now():
        raise UnauthorizedError("refresh token expired")
    if session_row.user_id is None:
        raise UnauthorizedError("refresh token has no user")

    user = await get_user_by_id(db, session_row.user_id)
    if user is None:
        raise UnauthorizedError("user no longer exists")

    session_row.revoked_at = now()
    return await _open_session(
        db,
        user=user,
        settings=s,
        ip_hash=session_row.ip_hash,
        ua_hash=session_row.ua_hash,
    )


async def logout(db: AsyncSession, refresh_token: str) -> None:
    """Revoke the session matching the supplied refresh token. Idempotent."""
    token_hash = hash_token(refresh_token)
    stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    session_row = (await db.execute(stmt)).scalar_one_or_none()
    if session_row is None:
        # Idempotent: unknown token is not an error — we don't leak existence.
        return
    if session_row.revoked_at is None:
        session_row.revoked_at = now()
        await db.flush()


async def _revoke_all_for_user(db: AsyncSession, user_id: str) -> None:
    stmt = select(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    )
    moment = now()
    for row in (await db.execute(stmt)).scalars():
        row.revoked_at = moment
    await db.flush()


async def verify_email(
    db: AsyncSession,
    *,
    token: str,
    settings: Settings | None = None,
) -> None:
    """Mark a user's email as verified from a signed ``email_verify`` token."""
    s = settings or get_settings()
    claims = authjwt.verify(token, expected_kind="email_verify", settings=s)
    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    if user.email_verified_at is None:
        user.email_verified_at = now()
        await db.flush()


async def current_user(
    db: AsyncSession,
    access_token: str,
    *,
    settings: Settings | None = None,
) -> User:
    """Resolve the currently-authenticated user from an access JWT."""
    s = settings or get_settings()
    claims = authjwt.verify(access_token, expected_kind="access", settings=s)
    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    return user


__all__ = [
    "GuestToken",
    "SessionTokens",
    "current_user",
    "guest_checkout",
    "login_password",
    "logout",
    "refresh_session",
    "register_user",
    "telegram_init_data_login",
    "telegram_widget_login",
    "verify_email",
]
