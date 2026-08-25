"""Pydantic DTOs for the wallet HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yupay.modules.evidence.schemas import ClientHints

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
    #: Validated same-origin by ``payments._safe_return_url``. Bounded like its
    #: sibling on ``PaymentIntentIn``: for Click this ends up inside the hosted
    #: checkout URL and is stored on the payment row, so an unbounded
    #: same-origin string is still a string we keep.
    return_url: str | None = Field(default=None, max_length=2048)
    #: Passive browser signals kept for chargeback defence (ADR-0044), the same
    #: ones checkout sends. A deposit needs them more than a sale does, not
    #: less: there are no goods, no delivery and no player id to point at, so
    #: the request context is most of what an acquirer can be shown.
    client_hints: ClientHints | None = None


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


#: Ledger metadata keys a customer may see. Everything a `wallet.post` call
#: writes today is otherwise internal: `reason` is the operator's note (the
#: admin UI asks for it as an audit entry), `credited_account` and `user_id`
#: are our own row ids, `external_id` is an acquirer handle, and `full` is a
#: refund bookkeeping flag. `provider` is the one a customer would recognise.
CUSTOMER_SAFE_METADATA: frozenset[str] = frozenset({"provider"})


class CustomerTransactionOut(BaseModel):
    """A ledger movement as the customer may see it.

    Deliberately not :class:`TransactionOut`. That one carries ``actor`` —
    ``admin:<uuid>`` for a manual adjustment — and the whole of
    ``extra_metadata``, which holds the note an operator writes while the admin
    UI tells them it is "видна в audit log". It reached the customer's history
    instead.

    The field names match ``TransactionOut`` so no client has to learn a second
    shape; what changes is what is in them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    reference_type: str | None
    reference_id: str | None
    #: Always ``None`` here. Who moved the money is an internal fact.
    actor: None = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    postings: list[PostingOut]

    @classmethod
    def from_transaction(cls, txn: Any) -> CustomerTransactionOut:
        """Build from a ``WalletTransaction``, keeping only safe metadata."""
        raw: dict[str, Any] = txn.extra_metadata or {}
        return cls(
            id=txn.id,
            kind=txn.kind,
            reference_type=txn.reference_type,
            reference_id=txn.reference_id,
            extra_metadata={k: v for k, v in raw.items() if k in CUSTOMER_SAFE_METADATA},
            created_at=txn.created_at,
            postings=[PostingOut.model_validate(p) for p in txn.postings],
        )


class CustomerTransactionListOut(BaseModel):
    items: list[CustomerTransactionOut]


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
    "CustomerTransactionListOut",
    "CustomerTransactionOut",
    "Direction",
    "OwnerType",
    "PostingOut",
    "TransactionListOut",
    "TransactionOut",
    "WalletOverviewOut",
    "WalletTopUpIn",
]
