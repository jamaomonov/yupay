"""Pydantic DTOs for the ``auth`` HTTP surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TelegramInitDataIn(BaseModel):
    """Body of ``POST /auth/telegram/webapp``."""

    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(min_length=1, max_length=8192)


class TelegramWidgetIn(BaseModel):
    """Body of ``POST /auth/telegram/widget``.

    Matches the JSON object Telegram's Login Widget posts to its ``data-onauth`` callback,
    plus the ``hash`` field.
    """

    model_config = ConfigDict(extra="allow")  # Telegram may add fields; we just verify the hash

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str = Field(min_length=64, max_length=64)


class GuestIn(BaseModel):
    """Body of ``POST /auth/guest``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class AdminDevLoginIn(BaseModel):
    """Body of ``POST /auth/admin-dev`` (dev-only login/password)."""

    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterIn(BaseModel):
    """Body of ``POST /auth/register``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    locale: str = Field(default="ru", max_length=8)


class LoginIn(BaseModel):
    """Body of ``POST /auth/login``."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class VerifyEmailIn(BaseModel):
    """Body of ``POST /auth/verify-email``."""

    token: str = Field(min_length=10, max_length=2048)


class ForgotPasswordIn(BaseModel):
    """Body of ``POST /auth/forgot-password``."""

    email: EmailStr


class ResetPasswordIn(BaseModel):
    """Body of ``POST /auth/reset-password``."""

    token: str = Field(min_length=10, max_length=2048)
    new_password: str = Field(min_length=8, max_length=200)


class TokensOut(BaseModel):
    """Response for any endpoint that mints a user session.

    The refresh token is intentionally absent: it is delivered as an ``HttpOnly``
    cookie (see :mod:`yupay.modules.auth.cookies`) so JS cannot read it. Only the
    short-lived access token — which the browser needs to attach as a Bearer header
    — is returned in the body.
    """

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 -- OAuth token-type literal, not a credential
    expires_in: int


class GuestTokenOut(BaseModel):
    """Response for the guest checkout endpoint."""

    access_token: str
    token_type: str = "Guest"  # noqa: S105 -- OAuth token-type literal, not a credential
    expires_in: int


class MeOut(BaseModel):
    """Response for ``GET /auth/me``."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    locale: str
    display_currency: str
    display_name: str | None
    photo_url: str | None
    roles: list[str] = []
    created_at: datetime


__all__ = [
    "AdminDevLoginIn",
    "ForgotPasswordIn",
    "GuestIn",
    "GuestTokenOut",
    "LoginIn",
    "MeOut",
    "RegisterIn",
    "ResetPasswordIn",
    "TelegramInitDataIn",
    "TelegramWidgetIn",
    "TokensOut",
    "VerifyEmailIn",
]
