"""Dev-only login: hardcoded credentials → admin JWT.

Disabled by default and **force-disabled in prod** regardless of settings. Used as a
stop-gap until the Telegram bot's domain is registered with BotFather.

Flow:

1. ``POST /api/v1/auth/admin-dev`` with ``{login, password}``.
2. The endpoint compares against ``Settings.admin_dev_login/password``.
3. A singleton ``users`` row with ``id = '__dev_admin__'`` is materialised on first
   call so the access JWT has a real ``sub`` and ``require_admin`` works against the
   same DB the rest of the app uses.
4. Tokens are minted via the same path as the Telegram flow.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ForbiddenError, UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.models import AuthSession
from yupay.modules.auth.security import constant_time_eq, hash_token, new_refresh_token
from yupay.modules.auth.service import SessionTokens
from yupay.modules.users.models import User

# Stable id for the dev-only admin row. Lives in production-shaped tables so all the
# guards (FK, audit) keep working without special-casing.
DEV_ADMIN_ID = "00000000-0000-7000-8000-000000000001"


def _dev_login_active(settings: Settings) -> bool:
    """Whether the dev-login endpoint is currently allowed to run."""
    return settings.admin_dev_login_enabled and not settings.is_prod


async def _ensure_dev_admin(db: AsyncSession) -> User:
    """Find-or-create the singleton dev admin row."""
    user = (await db.execute(select(User).where(User.id == DEV_ADMIN_ID))).scalar_one_or_none()
    if user is None:
        user = User(
            id=DEV_ADMIN_ID,
            email=None,
            locale="ru",
            display_name="Dev Admin",
            photo_url=None,
            roles=["admin"],
        )
        db.add(user)
        await db.flush()
        return user
    # Make sure the admin role is present even if someone revoked it earlier.
    if "admin" not in (user.roles or []):
        user.roles = sorted({*user.roles, "admin"})
    return user


async def dev_admin_login(
    db: AsyncSession,
    *,
    login: str,
    password: str,
    settings: Settings | None = None,
) -> SessionTokens:
    """Authenticate against the hardcoded dev creds and mint a session.

    Raises:
        ForbiddenError: when the endpoint is disabled by config, or when the configured
            credentials are still the compiled-in defaults (``admin``/``admin``).
        UnauthorizedError: on bad credentials.
    """
    s = settings or get_settings()
    if not _dev_login_active(s):
        raise ForbiddenError("dev login is disabled")

    # Refuse to run on the shipped defaults — an operator who enables the endpoint must
    # first set real credentials, or the "dev-only" door is an open admin backdoor.
    if s.admin_dev_login == "admin" and s.admin_dev_password == "admin":  # noqa: S105
        raise ForbiddenError("dev login refuses default credentials; set ADMIN_DEV_LOGIN/PASSWORD")

    # Constant-time comparison to keep the endpoint from leaking the credentials one
    # character at a time via response timing. Evaluate both halves before combining.
    login_ok = constant_time_eq(login, s.admin_dev_login)
    password_ok = constant_time_eq(password, s.admin_dev_password)
    if not (login_ok and password_ok):
        raise UnauthorizedError("invalid credentials")

    user = await _ensure_dev_admin(db)

    refresh = new_refresh_token()
    session_id = new_id()
    db.add(
        AuthSession(
            id=session_id,
            user_id=user.id,
            kind="user",
            refresh_token_hash=hash_token(refresh),
            expires_at=now() + timedelta(seconds=s.jwt_refresh_ttl_seconds),
        )
    )
    await db.flush()

    access = authjwt.mint_access(sub=user.id, sid=session_id, settings=s)
    return SessionTokens(
        access_token=access,
        refresh_token=refresh,
        access_expires_in=s.jwt_access_ttl_seconds,
        refresh_expires_in=s.jwt_refresh_ttl_seconds,
        user=user,
    )


__all__ = ["DEV_ADMIN_ID", "dev_admin_login"]
