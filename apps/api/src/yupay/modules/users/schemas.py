"""Pydantic DTOs for the ``users`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Keep in sync with the ``DISPLAY_CURRENCIES`` constant in
# ``apps/miniapp/src/lib/currency.ts``. Limited to what we can actually FX
# right now (see ``Settings.fx_supported_quotes``).
DisplayCurrencyLiteral = Literal["USD", "UZS", "RUB", "USDT"]


class UserOut(BaseModel):
    """User profile returned to authenticated clients."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    locale: str
    display_currency: str
    display_name: str | None
    photo_url: str | None
    roles: list[str] = []
    created_at: datetime


class UpdateMeIn(BaseModel):
    """Customer-facing ``PATCH /users/me`` body. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    display_currency: DisplayCurrencyLiteral | None = None
    locale: str | None = Field(default=None, max_length=8)


class TelegramLinkOut(BaseModel):
    """Telegram-link projection used in admin views."""

    model_config = ConfigDict(from_attributes=True)

    tg_user_id: int
    tg_username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    is_premium: bool
    last_seen_at: datetime


class UserAdminOut(BaseModel):
    """Admin-side user record with telegram and lifecycle fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    locale: str
    display_currency: str
    display_name: str | None
    photo_url: str | None
    roles: list[str] = []
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    telegram_link: TelegramLinkOut | None


class UserAdminListOut(BaseModel):
    """Paged list payload for ``GET /admin/users``."""

    items: list[UserAdminOut]
    total: int


class UserRolesIn(BaseModel):
    """Body of ``PATCH /admin/users/{id}/roles``."""

    model_config = ConfigDict(extra="forbid")

    # Open-ended for future roles (support, accountant…). Today only "admin" is
    # honored by ``require_admin``.
    roles: list[str] = Field(default_factory=list)


__all__ = [
    "DisplayCurrencyLiteral",
    "TelegramLinkOut",
    "UpdateMeIn",
    "UserAdminListOut",
    "UserAdminOut",
    "UserOut",
    "UserRolesIn",
]
