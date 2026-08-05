"""HTTP routes for the ``auth`` module.

Mounted under ``/api/v1/auth`` by :mod:`yupay.api.v1`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError
from yupay.core.logging import get_logger
from yupay.modules.auth.cookies import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    set_refresh_cookie,
)
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.dev_login import dev_admin_login
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.auth.schemas import (
    AdminDevLoginIn,
    ForgotPasswordIn,
    GuestIn,
    GuestTokenOut,
    LoginIn,
    MeOut,
    RegisterIn,
    RegisterOut,
    ResendVerificationIn,
    ResetPasswordIn,
    TelegramInitDataIn,
    TelegramWidgetIn,
    TokensOut,
    VerifyEmailIn,
)
from yupay.modules.auth.service import (
    SessionTokens,
    admin_telegram_widget_login,
    guest_checkout,
    login_password,
    logout,
    refresh_session,
    register_user,
    request_password_reset,
    resend_verification,
    reset_password,
    telegram_init_data_login,
    telegram_widget_login,
    verify_email,
)
from yupay.modules.auth.telegram import TelegramAuthError
from yupay.modules.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("yupay.auth.routes")


def _session_response(response: Response, tokens: SessionTokens) -> TokensOut:
    """Set the rotating refresh cookie and return the access token in the body.

    The refresh token never appears in the JSON body — it rides an ``HttpOnly``
    cookie so JS (and any XSS payload) cannot read it. See :mod:`.cookies`.
    """
    set_refresh_cookie(
        response,
        token=tokens.refresh_token,
        max_age=tokens.refresh_expires_in,
        settings=get_settings(),
    )
    return TokensOut(
        access_token=tokens.access_token,
        expires_in=tokens.access_expires_in,
    )


def _web_base(request: Request, locale: str) -> str:
    """Best-effort absolute web base for links in emails (e.g. https://host/ru)."""
    settings = get_settings()
    base = settings.web_base_url or str(request.base_url).rstrip("/")
    return f"{base.rstrip('/')}/{locale}"


@router.post(
    "/register",
    response_model=RegisterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an email/password account",
)
async def register_route(
    body: RegisterIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> RegisterOut:
    """Create an email/password account. No session is opened.

    The account must be verified (``POST /auth/verify-email``) before it can be
    used to log in — see ``login_password``'s ``EmailUnverifiedError`` gate.
    """
    # Per-IP throttle like login/forgot: registration sends a verification email
    # to an arbitrary address, so without this it is an unbounded
    # account-enumeration and verification-email-bomb relay.
    await guard_ip(request, bucket="register")
    user = await register_user(
        db,
        email=body.email,
        password=body.password,
        locale=body.locale,
        verify_link_base=_web_base(request, body.locale),
    )
    assert user.email is not None  # register_user always sets one from RegisterIn.email
    return RegisterOut(email=user.email)


@router.post(
    "/login",
    response_model=TokensOut,
    summary="Log in with email + password",
)
async def login_route(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Authenticate an existing email/password account and return a session."""
    await guard_ip(request, bucket="login")
    tokens = await login_password(db, email=body.email, password=body.password)
    return _session_response(response, tokens)


@router.post(
    "/telegram/webapp",
    response_model=TokensOut,
    summary="Authenticate a Telegram Mini App via initData",
)
async def login_telegram_webapp(
    body: TelegramInitDataIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Verify Telegram Mini App ``initData``, upsert the user, return a session."""
    try:
        tokens = await telegram_init_data_login(db, body.init_data)
    except TelegramAuthError as exc:
        log.info("auth.telegram.webapp.rejected", reason=str(exc))
        raise UnauthorizedError("telegram verification failed") from exc
    return _session_response(response, tokens)


@router.post(
    "/telegram/widget",
    response_model=TokensOut,
    summary="Authenticate via the Telegram Login Widget",
)
async def login_telegram_widget(
    body: TelegramWidgetIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Verify a Telegram Login Widget payload, upsert the user, return a session."""
    try:
        tokens = await telegram_widget_login(db, body.model_dump(exclude_none=True))
    except TelegramAuthError as exc:
        log.info("auth.telegram.widget.rejected", reason=str(exc))
        raise UnauthorizedError("telegram verification failed") from exc
    return _session_response(response, tokens)


@router.post(
    "/telegram/widget/admin",
    response_model=TokensOut,
    summary="Authenticate the admin panel via its dedicated Telegram Login Widget",
)
async def login_telegram_widget_admin(
    body: TelegramWidgetIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Verify an admin Login Widget payload (admin bot) and return a session.

    Verified against ``admin_telegram_bot_token`` (falls back to the customer bot
    token when unset). Non-admin users are rejected with 403.
    """
    try:
        tokens = await admin_telegram_widget_login(db, body.model_dump(exclude_none=True))
    except TelegramAuthError as exc:
        log.info("auth.telegram.widget.admin.rejected", reason=str(exc))
        raise UnauthorizedError("telegram verification failed") from exc
    return _session_response(response, tokens)


@router.post(
    "/guest",
    response_model=GuestTokenOut,
    summary="Mint a guest checkout token by email",
)
async def login_guest(
    body: GuestIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> GuestTokenOut:
    """Issue a short-lived guest token. No verification email is sent at MVP."""
    result = await guest_checkout(db, str(body.email))
    return GuestTokenOut(access_token=result.access_token, expires_in=result.expires_in)


@router.post(
    "/refresh",
    response_model=TokensOut,
    summary="Rotate a refresh token",
)
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokensOut:
    """Rotate-on-use: read the refresh from the ``HttpOnly`` cookie, mint a new pair.

    The client sends no body — the cookie carries the token (the request must be made
    with ``credentials: "include"``). A fresh refresh cookie is set on the response.
    """
    if not refresh_token:
        raise UnauthorizedError("missing refresh token")
    tokens = await refresh_session(db, refresh_token)
    return _session_response(response, tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
async def logout_route(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    authorization: Annotated[str | None, Header()] = None,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    """Idempotent: silently succeeds even if the token is unknown or already revoked.

    Reads the refresh token from the ``HttpOnly`` cookie and clears it. If the request
    also carries the access token (``Authorization: Bearer``) its ``jti`` is added to
    the revocation blocklist so it stops working immediately.
    """
    access_token: str | None = None
    if authorization:
        scheme, _, tok = authorization.partition(" ")
        if scheme == "Bearer" and tok.strip():
            access_token = tok.strip()
    await logout(db, refresh_token or "", access_token=access_token)
    clear_refresh_cookie(response, settings=get_settings())


@router.post(
    "/verify-email",
    response_model=TokensOut,
    summary="Confirm an email address from a signed token and open a session",
)
async def verify_email_route(
    body: VerifyEmailIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Mark the user's email as verified using a signed ``email_verify`` JWT, then log in."""
    tokens = await verify_email(db, token=body.token)
    return _session_response(response, tokens)


@router.post(
    "/resend-verification",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Resend the email-verification link (non-enumerating)",
)
async def resend_verification_route(
    body: ResendVerificationIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    """Non-enumerating: always returns 204 regardless of whether the email is known."""
    await guard_ip(request, bucket="resend-verification")
    await resend_verification(db, email=body.email, verify_link_base=_web_base(request, "ru"))


@router.post(
    "/password/forgot",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Request a password-reset email (non-enumerating)",
)
async def forgot_route(
    body: ForgotPasswordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    """Non-enumerating: always returns 204 regardless of whether the email is known."""
    await guard_ip(request, bucket="forgot")
    await request_password_reset(db, email=body.email, reset_link_base=_web_base(request, "ru"))


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password from a reset token",
)
async def reset_route(
    body: ResetPasswordIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    """Consume a single-use reset token and update the user's password."""
    await reset_password(db, token=body.token, new_password=body.new_password)


@router.get(
    "/me",
    response_model=MeOut,
    summary="Current authenticated user",
)
async def me(user: Annotated[User, Depends(current_user)]) -> MeOut:
    """Return the user record identified by the Bearer access token."""
    return MeOut.model_validate(user)


@router.post(
    "/admin-dev",
    response_model=TokensOut,
    summary="DEV-ONLY: login + password → admin JWT",
    description=(
        "Disabled by default. Set ``ADMIN_DEV_LOGIN_ENABLED=true`` in a non-prod "
        "environment to use. Force-disabled when ``ENVIRONMENT=prod`` regardless of "
        "the flag — the endpoint will return 403."
    ),
)
async def login_admin_dev(
    body: AdminDevLoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Stop-gap before BotFather domain is set up. See ``auth.dev_login``."""
    await guard_ip(request, bucket="admin-dev")
    settings = get_settings()
    tokens = await dev_admin_login(db, login=body.login, password=body.password, settings=settings)
    return _session_response(response, tokens)


@router.get(
    "/admin-dev/enabled",
    summary="DEV-ONLY: whether the dev login endpoint is active",
)
async def admin_dev_enabled() -> dict[str, bool]:
    """Lets the admin SPA decide whether to render the login/password form."""
    s = get_settings()
    return {"enabled": s.admin_dev_login_enabled and not s.is_prod}
