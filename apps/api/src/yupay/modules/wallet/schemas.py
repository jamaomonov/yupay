"""Pydantic DTOs for the wallet HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AccountKind = Literal[
    "user_wallet",
    "user_cashback",
    "user_promo_credit",
    "house_revenue",
    "house_cogs",
    "house_promo_expense",
    "house_payments_received",
    "house_refunds",
    "house_fx_pnl",
    "provider_clearing",
]

OwnerType = Literal["user", "house", "provider"]
Direction = Literal["D", "C"]
USER_VISIBLE_KINDS: tuple[AccountKind, ...] = (
    "user_wallet",
    "user_cashback",
    "user_promo_credit",
)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_type: OwnerType
    owner_id: str
    kind: AccountKind
    currency: str
    status: Literal["active", "frozen"]


class BalanceOut(BaseModel):
    account_id: str
    kind: AccountKind
    currency: str
    balance: Decimal


class WalletOverviewOut(BaseModel):
    """A user's view of their own ledger: one balance per (kind, currency)."""

    balances: list[BalanceOut]


class WalletTopUpIn(BaseModel):
    """Body of ``POST /api/v1/wallet/topup``. Currency is derived from ``provider``."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    provider: Annotated[str, Field(min_length=2, max_length=32)]
    #: Where the acquirer sends the customer back to. Without it the server
    #: falls back to ``{web_base_url}/checkout/return``, which is generic by
    #: design — a deposit wants to land on the balance it just changed.
    #: Validated same-origin by ``payments._safe_return_url``.
    return_url: str | None = None


class PostingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    direction: Direction
    amount: Decimal
    currency: str
    created_at: datetime


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    reference_type: str | None
    reference_id: str | None
    actor: str | None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    postings: list[PostingOut]


class TransactionListOut(BaseModel):
    items: list[TransactionOut]


class AdminAdjustIn(BaseModel):
    """Body of ``POST /admin/wallet/adjust``.

    Posts: ``D house_promo_expense :: C user_<kind>`` for ``amount > 0`` (credit user),
    or the reverse for ``amount < 0`` (debit user — clawback).
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    kind: Literal["user_wallet", "user_cashback", "user_promo_credit"]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    amount: Decimal = Field(description="Signed minor-unit amount. Positive = credit user.")
    reason: Annotated[str, Field(min_length=4, max_length=500)]
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class AdminAccountListOut(BaseModel):
    items: list[AccountOut]


class AdminAccountWithBalanceOut(AccountOut):
    balance: Decimal


class AdminUserLedgerOut(BaseModel):
    user_id: str
    accounts: list[AdminAccountWithBalanceOut]
    recent_transactions: list[TransactionOut]


__all__ = [
    "USER_VISIBLE_KINDS",
    "AccountKind",
    "AccountOut",
    "AdminAccountListOut",
    "AdminAccountWithBalanceOut",
    "AdminAdjustIn",
    "AdminUserLedgerOut",
    "BalanceOut",
    "Direction",
    "OwnerType",
    "PostingOut",
    "TransactionListOut",
    "TransactionOut",
    "WalletOverviewOut",
    "WalletTopUpIn",
]
