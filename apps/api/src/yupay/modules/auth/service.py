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
from yupay.core.errors import (
    AccountSuspendedError,
    ConflictError,
    EmailUnverifiedError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from yupay.core.ids import new_id
from yupay.core.redis import get_redis
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
from yupay.modules.notifications.service import schedule
from yupay.modules.notifications.templates import (
    EmailContent,
    password_reset_email,
    verify_email_email,
)
from yupay.modules.users.models import User
from yupay.modules.users.service import (
    get_user_by_id,
    upsert_user_by_telegram,
)

# A pre-computed argon2id hash of a throwaway password. ``login_password`` verifies
# against this when the account is absent (or has no password) so the response time is
# indistinguishable from a wrong-password attempt on a real account — closing the
# account-enumeration timing side-channel.
_DUMMY_HASH = hash_password("x")


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
    """Create a fresh ``auth_sessions`` row and mint matching access + refresh.

    Every way into an account converges here — password, both Telegram flows,
    dev login, and refresh rotation — which makes it the one place worth
    checking the ban. Handing a suspended account a token that ``current_user``
    would reject on the next call is worse than refusing here: the customer sees
    a working login followed by a broken app, instead of being told why.
    """
    if user.banned_at is not None:
        raise AccountSuspendedError("this account has been suspended")
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
) -> User:
    """Create an email/password user and send a verify email. No session is opened.

    The account exists immediately but cannot be used for password login until
    the emailed link is followed (``verify_email``, which does open a session)
    — see ``login_password``'s ``EmailUnverifiedError`` gate.

    Args:
        db: Async session.
        email: New account email (uniqueness enforced by ``uq_users_email_alive``).
        password: Plaintext password (hashed with argon2id).
        locale: Preferred locale for the account.
        settings: Optional settings override.
        verify_link_base: Absolute URL prefix for the verification link, e.g.
            ``https://yupay.uz/ru``. When ``None`` no email is sent (dev).

    Returns:
        The newly created user row.

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

    return user


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
        EmailUnverifiedError: On correct credentials for an account whose email
            has not been verified yet (see ``verify_email``). Telegram/guest/dev
            logins are not affected by this check.
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    stmt = select(User).where(
        User.email == normalised,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    # Always run a verify — against the real hash when we have one, otherwise against a
    # constant dummy hash — so an absent/Telegram-only account can't be distinguished
    # from a wrong password by response time. Result is discarded in those branches.
    stored_hash = user.password_hash if (user is not None and user.password_hash) else _DUMMY_HASH
    password_ok = verify_password(password, stored_hash)
    if user is None or not user.password_hash or not password_ok:
        raise UnauthorizedError("invalid email or password")
    if user.email_verified_at is None:
        raise EmailUnverifiedError("Confirm your email address before signing in.")
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
    await tg.enforce_widget_single_use(
        widget_hash=verified.hash,
        auth_date=verified.auth_date,
        max_age_seconds=s.telegram_init_data_ttl_seconds,
    )
    user = await upsert_user_by_telegram(db, verified.user)
    return await _open_session(db, user=user, settings=s)


async def admin_telegram_widget_login(
    db: AsyncSession,
    payload: dict[str, str | int | bool],
    *,
    settings: Settings | None = None,
) -> SessionTokens:
    """Verify an **admin** Login Widget payload and open a session.

    The admin SPA embeds a Login Widget for a dedicated admin bot (domain-bound to
    the admin panel). The payload is therefore signed with the admin bot's token,
    so it is verified against ``admin_telegram_bot_token`` (falling back to
    ``telegram_bot_token`` when the admin bot is not configured yet).

    Only users carrying the ``admin`` role may mint a session here — the admin
    login surface refuses non-admins outright rather than handing out a token that
    every admin route would 403 anyway.

    Raises:
        ForbiddenError: When the verified user is not an admin.
    """
    s = settings or get_settings()
    bot_token = s.admin_telegram_bot_token or s.telegram_bot_token
    if not bot_token:
        raise RuntimeError("ADMIN_TELEGRAM_BOT_TOKEN / TELEGRAM_BOT_TOKEN is not configured")

    verified = tg.verify_login_widget(
        payload,
        bot_token=bot_token,
        max_age_seconds=s.telegram_init_data_ttl_seconds,
    )
    await tg.enforce_widget_single_use(
        widget_hash=verified.hash,
        auth_date=verified.auth_date,
        max_age_seconds=s.telegram_init_data_ttl_seconds,
    )
    user = await upsert_user_by_telegram(db, verified.user)
    if "admin" not in (user.roles or []):
        raise ForbiddenError("admin role required")
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

    # FOR UPDATE closes a rotation TOCTOU: without the row lock, two requests
    # presenting the same refresh token both read ``revoked_at IS NULL``, both
    # pass the reuse check, and both mint a new session — defeating the ADR-0007
    # reuse trip-wire. The lock serialises them: the loser blocks here, then
    # sees the now-revoked row and trips reuse detection.
    stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash).with_for_update()
    session_row = (await db.execute(stmt)).scalar_one_or_none()
    if session_row is None:
        raise UnauthorizedError("invalid refresh token")

    if session_row.revoked_at is not None:
        # Reuse detected — burn down the user's other sessions to limit blast radius.
        if session_row.user_id is not None:
            await _revoke_all_for_user(db, session_row.user_id, settings=s)
        raise UnauthorizedError("refresh token reuse detected")

    if session_row.expires_at <= now():
        raise UnauthorizedError("refresh token expired")
    if session_row.user_id is None:
        raise UnauthorizedError("refresh token has no user")

    user = await get_user_by_id(db, session_row.user_id)
    if user is None:
        raise UnauthorizedError("user no longer exists")

    session_row.revoked_at = now()
    # The rotated-out session's access token dies immediately, not after 15 min.
    await _blocklist_session_id(session_row.id, settings=s)
    return await _open_session(
        db,
        user=user,
        settings=s,
        ip_hash=session_row.ip_hash,
        ua_hash=session_row.ua_hash,
    )


async def _blocklist_access_token(access_token: str, *, settings: Settings) -> None:
    """Add a still-valid access token's ``jti`` to the Redis revocation blocklist.

    Best-effort: an invalid/expired token has nothing to revoke and is ignored. The
    marker TTL equals the token's remaining lifetime (≤ ``jwt_access_ttl_seconds``, so
    ≤ 15 min) — once the token would expire on its own the key can safely disappear.
    Mirrors the ``auth:pwreset:{jti}`` Redis pattern used by ``reset_password``.
    """
    try:
        claims = authjwt.verify(access_token, expected_kind="access", settings=settings)
    except UnauthorizedError:
        return
    ttl = int((claims.exp - now()).total_seconds())
    if ttl <= 0:
        return
    await get_redis().set(f"auth:revoked:{claims.jti}", "1", ex=ttl)


async def _blocklist_session_id(sid: str, *, settings: Settings) -> None:
    """Kill every outstanding access token for a revoked session immediately.

    Access tokens carry ``sid`` and live up to their full lifetime (15 min)
    independently of their session row, and were only ever checked against the
    per-``jti`` blocklist — which is populated solely by an explicit ``logout``
    that presents the access token. So revoking a session by any other means
    (rotation, reuse-detection, password-reset revoke-all, logout without the
    access token) left its access tokens usable until they expired on their own.

    Drop a ``auth:revoked_sid`` marker that ``current_user`` checks per request.
    TTL = the access-token lifetime, so once the token would expire anyway the
    marker can disappear. Mirrors the per-``jti`` ``auth:revoked`` blocklist.
    """
    await get_redis().set(f"auth:revoked_sid:{sid}", "1", ex=settings.jwt_access_ttl_seconds)


async def logout(
    db: AsyncSession,
    refresh_token: str,
    *,
    access_token: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Revoke the session matching the supplied refresh token. Idempotent.

    When the caller also presents the access token (``Authorization: Bearer`` on the
    logout request), its ``jti`` is added to the ``auth:revoked`` blocklist so the
    already-issued access token stops working immediately rather than lingering for up
    to its 15-minute lifetime.
    """
    s = settings or get_settings()
    if access_token:
        await _blocklist_access_token(access_token, settings=s)
    token_hash = hash_token(refresh_token)
    stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    session_row = (await db.execute(stmt)).scalar_one_or_none()
    if session_row is None:
        # Idempotent: unknown token is not an error — we don't leak existence.
        return
    if session_row.revoked_at is None:
        session_row.revoked_at = now()
        # Kill this session's access token too, even when the caller didn't
        # present it (cookie-only logout) — access_token above only covers the
        # case where it was on the request.
        await _blocklist_session_id(session_row.id, settings=s)
        await db.flush()


async def _revoke_all_for_user(
    db: AsyncSession, user_id: str, *, settings: Settings | None = None
) -> None:
    s = settings or get_settings()
    stmt = select(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    )
    moment = now()
    for row in (await db.execute(stmt)).scalars():
        row.revoked_at = moment
        # Outstanding access tokens for each revoked session die immediately.
        await _blocklist_session_id(row.id, settings=s)
    await db.flush()


async def verify_email(
    db: AsyncSession,
    *,
    token: str,
    settings: Settings | None = None,
) -> SessionTokens:
    """Consume a single-use ``email_verify`` token, mark the email verified, then log in.

    The link flow ends in a usable session rather than dropping the user back
    to a login form immediately after they've proven the address is theirs.

    The single-use guarantee is enforced via a Redis ``SET NX`` on a key
    derived from the token's ``jti`` — the same mechanism ``reset_password``
    uses for ``password_reset`` tokens. Without it, a leaked/forwarded verify
    link would mint a fresh session on every hit for the token's full TTL
    (``jwt_email_token_ttl_seconds``): a repeatable magic-login link.

    Raises:
        UnauthorizedError: On an invalid/expired token or one already consumed.
        NotFoundError: If the user referenced by the token no longer exists.
    """
    s = settings or get_settings()
    claims = authjwt.verify(token, expected_kind="email_verify", settings=s)

    redis = get_redis()
    marker = f"auth:emailverify:{claims.jti}"
    # redis-py returns True on successful SET NX, None when the key already exists.
    was_set = await redis.set(marker, "1", ex=s.jwt_email_token_ttl_seconds, nx=True)
    if not was_set:
        raise UnauthorizedError("verification token already used")

    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    if user.email_verified_at is None:
        user.email_verified_at = now()
        await db.flush()
    return await _open_session(db, user=user, settings=s)


async def resend_verification(
    db: AsyncSession,
    *,
    email: str,
    settings: Settings | None = None,
    verify_link_base: str | None = None,
) -> None:
    """Re-send the verify-email link if the account exists and is unverified.

    Never reveals whether the email exists or its verification state (no
    enumeration): the caller returns 204 regardless of what happened here.
    Crucially, this must hold for *latency* too — see ``_deliver_verify_email``.

    Args:
        db: Async database session.
        email: The email address to look up.
        settings: Optional settings override.
        verify_link_base: Absolute URL prefix for the verification link, e.g.
            ``https://yupay.uz/ru``. When ``None`` no email is sent (dev).
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    stmt = select(User).where(
        User.email == normalised,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or user.email_verified_at is not None or not verify_link_base:
        return
    token = authjwt.mint_email_verify(sub=user.id, settings=s)
    link = f"{verify_link_base.rstrip('/')}/auth/verify?token={token}"
    content = verify_email_email(link=link)
    # Dispatch fire-and-forget, exactly like ``request_password_reset`` (there is
    # no Dramatiq email actor; the notifications module's ``schedule`` helper runs
    # the coroutine off the request path). This closes two problems at once: (1)
    # the §10 "no synchronous outbound HTTP in a request handler" rule, and (2) an
    # enumeration timing leak — without this, the known+unverified branch alone
    # would add a blocking network round-trip that the unknown-email and
    # already-verified branches lack, letting response latency (not just
    # status/body) distinguish "this email exists and is unverified" from the rest.
    schedule(_deliver_verify_email(to=normalised, content=content))


async def _deliver_verify_email(*, to: str, content: EmailContent) -> bool:
    """Send a verify-email link in the background. Errors are swallowed by ``schedule``."""
    with contextlib.suppress(EmailSendError):
        await send_email(to=to, subject=content.subject, html=content.html, text=content.text)
    return True


async def current_user(
    db: AsyncSession,
    access_token: str,
    *,
    settings: Settings | None = None,
) -> User:
    """Resolve the currently-authenticated user from an access JWT."""
    s = settings or get_settings()
    claims = authjwt.verify(access_token, expected_kind="access", settings=s)
    # ADR-0007 access-token blocklist: a single Redis GET per request. A jti lands
    # here when the session is explicitly revoked (logout). See ``_blocklist_access_token``.
    if await get_redis().get(f"auth:revoked:{claims.jti}") is not None:
        raise UnauthorizedError("token revoked")
    # ADR-0007 session-level revocation: a revoked session (rotation, logout,
    # reuse-detection, password reset) blocklists its ``sid`` so its still-valid
    # access tokens stop working at once instead of lingering up to 15 min.
    if claims.sid is not None and (
        await get_redis().get(f"auth:revoked_sid:{claims.sid}") is not None
    ):
        raise UnauthorizedError("session revoked")
    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    # Checked here rather than by revoking sessions on ban: this is the single
    # gate every authenticated request already passes through, so a ban takes
    # effect on the customer's very next call — including with an access token
    # minted seconds earlier. One mechanism, nothing to keep in sync (ADR-0045).
    if user.banned_at is not None:
        raise AccountSuspendedError("this account has been suspended")
    return user


async def request_password_reset(
    db: AsyncSession,
    *,
    email: str,
    settings: Settings | None = None,
    reset_link_base: str | None = None,
) -> None:
    """Send a reset link if the email maps to a password account. Always silent.

    Never reveals whether the email exists (no enumeration): the caller returns
    204 regardless.

    Args:
        db: Async database session.
        email: The email address to look up.
        settings: Optional settings override.
        reset_link_base: Absolute URL prefix for the reset link, e.g.
            ``https://yupay.uz/ru``. When ``None`` no email is sent (dev).
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    stmt = select(User).where(
        User.email == normalised,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.password_hash or not reset_link_base:
        return
    token = authjwt.mint_password_reset(sub=user.id, settings=s)
    link = f"{reset_link_base.rstrip('/')}/auth/reset?token={token}"
    content = password_reset_email(link=link)
    # Dispatch fire-and-forget (there is no Dramatiq email actor; the notifications
    # module's ``schedule`` helper runs the coroutine off the request path). This
    # closes two problems at once: (1) the §10 "no synchronous outbound HTTP in a
    # request handler" rule, and (2) the enumeration timing leak — the known-email
    # branch no longer adds a blocking network round-trip that an unknown email lacks.
    schedule(_deliver_reset_email(to=normalised, content=content))


async def _deliver_reset_email(*, to: str, content: EmailContent) -> bool:
    """Send a password-reset email in the background. Errors are swallowed by ``schedule``."""
    with contextlib.suppress(EmailSendError):
        await send_email(to=to, subject=content.subject, html=content.html, text=content.text)
    return True


async def reset_password(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
    settings: Settings | None = None,
) -> None:
    """Consume a single-use reset token, set a new password, revoke sessions.

    The single-use guarantee is enforced via a Redis ``SET NX`` on a key
    derived from the token's ``jti``. On first use the key is set and the
    password is updated; on any subsequent call the key is already present
    so ``SET NX`` returns ``None``, triggering ``UnauthorizedError``.

    Args:
        db: Async database session.
        token: Signed ``password_reset`` JWT.
        new_password: Plaintext replacement password (hashed with argon2id).
        settings: Optional settings override.

    Raises:
        UnauthorizedError: On an invalid/expired token or one already consumed.
        NotFoundError: If the user referenced by the token no longer exists.
    """
    s = settings or get_settings()
    claims = authjwt.verify(token, expected_kind="password_reset", settings=s)

    redis = get_redis()
    marker = f"auth:pwreset:{claims.jti}"
    # redis-py returns True on successful SET NX, None when the key already exists.
    was_set = await redis.set(marker, "1", ex=s.jwt_email_token_ttl_seconds, nx=True)
    if not was_set:
        raise UnauthorizedError("reset token already used")

    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    user.password_hash = hash_password(new_password)
    await db.flush()
    await _revoke_all_for_user(db, user.id, settings=s)


__all__ = [
    "GuestToken",
    "SessionTokens",
    "admin_telegram_widget_login",
    "current_user",
    "guest_checkout",
    "login_password",
    "logout",
    "refresh_session",
    "register_user",
    "request_password_reset",
    "resend_verification",
    "reset_password",
    "telegram_init_data_login",
    "telegram_widget_login",
    "verify_email",
]
