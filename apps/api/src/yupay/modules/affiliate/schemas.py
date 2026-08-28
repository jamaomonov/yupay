"""Wire shapes for the buyer-facing affiliate endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from yupay.modules.affiliate.discount import DiscountRejection
from yupay.modules.affiliate.models import AffiliatePayout
from yupay.modules.orders.schemas import OrderItemIn


class PreviewIn(BaseModel):
    """A code and the cart it would apply to."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    currency: str = Field(min_length=3, max_length=8, default="USD")
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)


class PreviewOut(BaseModel):
    """Whether the code applies, and what it would do to the total.

    ``reason`` is only set when ``applicable`` is false, and it is deliberately
    coarse: a code that does not exist, one that is switched off, and one whose
    partner is suspended all report ``unknown``. Telling them apart would make
    this endpoint a lookup service for other people's promo codes.

    The amounts are for display. The order is priced again when it is actually
    created, so a code deactivated in between cannot be spent at the price
    shown here.
    """

    applicable: bool
    reason: DiscountRejection | None = None
    code: str | None = None
    percent: Decimal | None = None
    currency: str
    total_before: Decimal
    total_after: Decimal
    discount: Decimal


class ApplicationIn(BaseModel):
    """A request to join the program."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str | None = Field(default=None, max_length=128)
    contact: str | None = Field(default=None, max_length=128)
    channel: str | None = Field(default=None, max_length=512)


class ApplicationOut(BaseModel):
    """Deliberately contentless.

    Answering "you already applied" — or returning the row — would let anyone
    with an address list discover which of them are partners. The endpoint
    accepts and says so; nothing more.
    """

    accepted: bool = True


class SetPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=2048)
    password: str = Field(min_length=8, max_length=256)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=512)


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 -- OAuth token-type literal, not a credential
    expires_in: int


class CodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    discount_percent: Decimal
    commission_percent: Decimal
    active: bool
    created_at: datetime


class ProfileOut(BaseModel):
    """The partner, and the codes they promote.

    No ``password_hash``, and no ``admin_note`` — the second is an internal
    remark about the partner, not something to hand back to them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None
    contact: str | None
    channel: str | None
    status: str
    created_at: datetime
    codes: list[CodeOut] = Field(default_factory=list)


class StatsOut(BaseModel):
    """Earnings over a rolling window.

    ``period`` names the window and ``since`` says where it starts, because
    "month" here means the last 30 days rather than the calendar month — see
    ``affiliate.panel`` for why.
    """

    period: str
    since: datetime
    earned: Decimal
    orders: int
    activations: int


class BalanceOut(BaseModel):
    """Straight from the ledger.

    ``available`` is the only figure a withdrawal can draw on. ``held`` is
    commission still inside its hold period; ``reserved`` is already claimed by
    an open request.
    """

    currency: str
    available: Decimal
    held: Decimal
    reserved: Decimal


class CommissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    base_amount: Decimal
    percent: Decimal
    amount: Decimal
    currency: str
    status: str
    available_at: datetime
    created_at: datetime


class CommissionListOut(BaseModel):
    items: list[CommissionOut]
    total: int


class PayoutRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0)
    card_number: str = Field(min_length=12, max_length=32)
    card_holder: str = Field(min_length=1, max_length=128)


class PayoutOut(BaseModel):
    """A withdrawal, as the partner sees it.

    The card number is masked to its last four digits. The partner already
    knows which card they typed, and a full PAN in a JSON response is a PAN in
    a browser cache, a proxy log and a screenshot.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    amount: Decimal
    currency: str
    card_last4: str
    card_holder: str
    status: str
    admin_note: str | None
    created_at: datetime
    processed_at: datetime | None

    @classmethod
    def from_row(cls, row: AffiliatePayout) -> PayoutOut:
        """Build from a model row, masking the card."""
        return cls(
            id=row.id,
            amount=row.amount,
            currency=row.currency,
            card_last4=row.card_number[-4:],
            card_holder=row.card_holder,
            status=row.status,
            admin_note=row.admin_note,
            created_at=row.created_at,
            processed_at=row.processed_at,
        )


class PayoutListOut(BaseModel):
    items: list[PayoutOut]


__all__ = [
    "ApplicationIn",
    "ApplicationOut",
    "BalanceOut",
    "CodeOut",
    "CommissionListOut",
    "CommissionOut",
    "LoginIn",
    "PayoutListOut",
    "PayoutOut",
    "PayoutRequestIn",
    "PreviewIn",
    "PreviewOut",
    "ProfileOut",
    "RefreshIn",
    "SetPasswordIn",
    "StatsOut",
    "TokensOut",
]
