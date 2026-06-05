"""HTTP routes for the ``auth`` module.

Mounted under ``/api/v1/auth`` by :mod:`yupay.api.v1`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError
from yupay.core.logging import get_logger
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.dev_login import dev_admin_login
from yupay.modules.auth.schemas import (
    AdminDevLoginIn,
    GuestIn,
    GuestTokenOut,
    LoginIn,
    LogoutIn,
    MeOut,
    RefreshIn,
    RegisterIn,
    TelegramInitDataIn,
    TelegramWidgetIn,
    TokensOut,
)
from yupay.modules.auth.service import (
    SessionTokens,
    guest_checkout,
    login_password,
    logout,
    refresh_session,
    register_user,
    telegram_init_data_login,
    telegram_widget_login,
)
from yupay.modules.auth.telegram import TelegramAuthError
from yupay.modules.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("yupay.auth.routes")


def _tokens_response(tokens: SessionTokens) -> TokensOut:
    return TokensOut(
        access_token=tokens.access_token,
        expires_in=tokens.access_expires_in,
        refresh_token=tokens.refresh_token,
        refresh_expires_in=tokens.refresh_expires_in,
    )


def _web_base(request: Request, locale: str) -> str:
    """Best-effort absolute web base for links in emails (e.g. https://host/ru)."""
    settings = get_settings()
    base = settings.web_base_url or str(request.base_url).rstrip("/")
    return f"{base.rstrip('/')}/{locale}"


@router.post(
    "/register",
    response_model=TokensOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an email/password account",
)
async def register_route(
    body: RegisterIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Create an email/password account and return a session immediately."""
    tokens = await register_user(
        db,
        email=body.email,
        password=body.password,
        locale=body.locale,
        verify_link_base=_web_base(request, body.locale),
    )
    return _tokens_response(tokens)


@router.post(
    "/login",
    response_model=TokensOut,
    summary="Log in with email + password",
)
async def login_route(
    body: LoginIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Authenticate an existing email/password account and return a session."""
    tokens = await login_password(db, email=body.email, password=body.password)
    return _tokens_response(tokens)


@router.post(
    "/telegram/webapp",
    response_model=TokensOut,
    summary="Authenticate a Telegram Mini App via initData",
)
async def login_telegram_webapp(
    body: TelegramInitDataIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Verify Telegram Mini App ``initData``, upsert the user, return a session."""
    try:
        tokens = await telegram_init_data_login(db, body.init_data)
    except TelegramAuthError as exc:
        log.info("auth.telegram.webapp.rejected", reason=str(exc))
        raise UnauthorizedError("telegram verification failed") from exc
    return _tokens_response(tokens)


@router.post(
    "/telegram/widget",
    response_model=TokensOut,
    summary="Authenticate via the Telegram Login Widget",
)
async def login_telegram_widget(
    body: TelegramWidgetIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Verify a Telegram Login Widget payload, upsert the user, return a session."""
    try:
        tokens = await telegram_widget_login(db, body.model_dump(exclude_none=True))
    except TelegramAuthError as exc:
        log.info("auth.telegram.widget.rejected", reason=str(exc))
        raise UnauthorizedError("telegram verification failed") from exc
    return _tokens_response(tokens)


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
    body: RefreshIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Rotate-on-use: revoke the supplied refresh, mint a new pair."""
    tokens = await refresh_session(db, body.refresh_token)
    return _tokens_response(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
async def logout_route(
    body: LogoutIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    """Idempotent: silently succeeds even if the token is unknown or already revoked."""
    await logout(db, body.refresh_token)


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
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Stop-gap before BotFather domain is set up. See ``auth.dev_login``."""
    settings = get_settings()
    tokens = await dev_admin_login(db, login=body.login, password=body.password, settings=settings)
    return _tokens_response(tokens)


@router.get(
    "/admin-dev/enabled",
    summary="DEV-ONLY: whether the dev login endpoint is active",
)
async def admin_dev_enabled() -> dict[str, bool]:
    """Lets the admin SPA decide whether to render the login/password form."""
    s = get_settings()
    return {"enabled": s.admin_dev_login_enabled and not s.is_prod}
