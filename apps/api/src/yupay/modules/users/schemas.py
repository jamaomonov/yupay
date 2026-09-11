"""Pydantic DTOs for the ``users`` module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Sort keys for ``GET /admin/users``. Wallet sorts convert non-USD balances
# through the latest ``fx_rates`` row (USD/USDT 1:1); created is the default.
UserAdminSort = Literal[
    "created_desc",
    "created_asc",
    "wallet_desc",
    "wallet_asc",
    "name_asc",
    "name_desc",
]

# Keep in sync with the ``DISPLAY_CURRENCIES`` constant in
# ``apps/miniapp/src/lib/currency.ts``. Limited to what we can actually FX
# right now (see ``Settings.fx_supported_quotes``).
DisplayCurrencyLiteral = Literal["USD", "UZS", "RUB", "USDT"]

# Locales the storefront ships UI translations for. Keep in sync with
# ``LOCALES`` in ``packages/i18n/src/index.ts`` and the miniapp catalogs.
LocaleLiteral = Literal["ru", "en", "uz"]


def _coerce_roles(value: Any) -> Any:
    """Coerce a malformed ``roles`` value to ``[]`` instead of failing validation.

    The column defaults to ``'[]'::jsonb`` but legacy/edge rows have been seen
    holding ``{}`` (a JSON object) rather than a list. That should never crash
    ``GET /admin/users`` — treat it as "no roles" instead.
    """
    if not isinstance(value, list):
        return []
    return value


class UserOut(BaseModel):
    """User profile returned to authenticated clients."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    #: Where this customer's order mail goes. Distinct from ``email``, which
    #: is the login identity — a settings screen writes this one, never that.
    delivery_email: EmailStr | None = None
    locale: str
    display_currency: str
    display_name: str | None
    photo_url: str | None
    roles: list[str] = []
    created_at: datetime

    _coerce_roles = field_validator("roles", mode="before")(_coerce_roles)


class UpdateMeIn(BaseModel):
    """Customer-facing ``PATCH /users/me`` body. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    display_currency: DisplayCurrencyLiteral | None = None
    locale: LocaleLiteral | None = None
    #: Where to mail orders. ``None`` leaves it untouched (partial patch);
    #: an empty string clears it, which is the only way back to "use my
    #: account address" once one has been set.
    delivery_email: EmailStr | Literal[""] | None = None


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


class SteamLinkOut(BaseModel):
    """Steam-link projection used in admin views."""

    model_config = ConfigDict(from_attributes=True)

    steam_id: int
    persona_name: str | None
    avatar_url: str | None


class UserWalletBalanceOut(BaseModel):
    """One ``user_wallet`` balance, in the account's own currency.

    ``balance`` is major units as a Decimal, same wire shape as Customer 360.
    """

    model_config = ConfigDict(frozen=True)

    currency: str
    balance: Decimal


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
    banned_at: datetime | None = None
    ban_reason: str | None = None
    banned_by: str | None = None
    telegram_link: TelegramLinkOut | None
    steam_link: SteamLinkOut | None = None
    #: Spendable ``user_wallet`` balances. Empty when the user has no account
    #: or a zeroed one. Populated on the list; other admin user endpoints
    #: leave it as ``[]`` (Customer 360 carries the full ledger).
    wallet_balances: list[UserWalletBalanceOut] = Field(default_factory=list)

    _coerce_roles = field_validator("roles", mode="before")(_coerce_roles)


class UserAdminListOut(BaseModel):
    """Paged list payload for ``GET /admin/users``."""

    items: list[UserAdminOut]
    total: int
    #: Global ``user_wallet`` liability, one bucket per currency. Independent
    #: of ``search`` / pagination — this is "how much customer money we hold".
    wallet_totals: list[UserWalletBalanceOut] = Field(default_factory=list)


class BanUserIn(BaseModel):
    """Body of ``POST /admin/users/{id}/ban``.

    The reason is optional but strongly encouraged: it is the only thing that
    will explain the suspension to whoever looks at the account in six months,
    including the admin who created it.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class UserRolesIn(BaseModel):
    """Body of ``PATCH /admin/users/{id}/roles``."""

    model_config = ConfigDict(extra="forbid")

    # Open-ended for future roles (support, accountant…). Today only "admin" is
    # honored by ``require_admin``.
    roles: list[str] = Field(default_factory=list)


__all__ = [
    "DisplayCurrencyLiteral",
    "LocaleLiteral",
    "TelegramLinkOut",
    "UpdateMeIn",
    "UserAdminListOut",
    "UserAdminOut",
    "UserAdminSort",
    "UserOut",
    "UserRolesIn",
    "UserWalletBalanceOut",
]
