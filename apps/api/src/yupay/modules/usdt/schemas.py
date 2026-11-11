"""Wire shapes for the USDT top-up routes (cabinet and admin)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from yupay.modules.merchants.machine_schemas import UsdAmount

UsdtMode = Literal["off", "allowlist", "all"]
UsdtResult = Literal["matched", "unmatched", "ignored", "manual", "dismissed"]


class UsdtStatusOut(BaseModel):
    """Whether the cabinet should offer a USDT top-up, and its bounds."""

    enabled: bool
    network: str = "TRC20"
    min_amount: UsdAmount | None
    max_amount: UsdAmount | None


class UsdtDepositIn(BaseModel):
    """Request to reserve an amount, in USDT with at most two decimals."""

    amount: Decimal = Field(gt=0, le=Decimal("1000000"), decimal_places=2)


class UsdtDepositOut(BaseModel):
    """One top-up reservation. ``address`` is set only while it is pending."""

    number: str
    status: str
    amount: UsdAmount
    network: str = "TRC20"
    address: str | None
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    tx_id: str | None = Field(description="The paying transaction, once paid.")


class UsdtDepositsOut(BaseModel):
    """A page of top-ups, newest first; items never carry the address."""

    items: list[UsdtDepositOut]
    next_cursor: str | None


# --- admin -----------------------------------------------------------------


class UsdtSettingsOut(BaseModel):
    """The USDT switch row."""

    mode: UsdtMode
    allowlist_merchant_ids: list[str]
    address: str | None
    min_amount_usd: UsdAmount
    max_amount_usd: UsdAmount
    cursor_block_ms: int | None = Field(description="Read-only: where the next poll starts.")
    updated_at: datetime


class UsdtSettingsIn(BaseModel):
    """Partial update of the switch row; absent fields are left alone."""

    mode: UsdtMode | None = None
    allowlist_merchant_ids: list[str] | None = None
    address: str | None = None
    min_amount_usd: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    max_amount_usd: Decimal | None = Field(default=None, gt=0, decimal_places=2)


class UsdtIncomingOut(BaseModel):
    """One journal row: a confirmed transfer to our address."""

    id: str
    tx_id: str
    from_address: str
    amount_usdt: Decimal
    block_at: datetime
    received_at: datetime
    result: UsdtResult
    reservation_number: str | None
    merchant_id: str | None
    merchant_title: str | None
    note: str | None
    resolved_at: datetime | None


class UsdtIncomingPageOut(BaseModel):
    """A page of the journal, newest first."""

    items: list[UsdtIncomingOut]
    next_cursor: str | None


class UsdtCreditIn(BaseModel):
    """Credit an unmatched transfer to a reseller by hand."""

    merchant_id: str
    note: str | None = Field(default=None, max_length=256)


class UsdtDismissIn(BaseModel):
    """Close an unmatched transfer without crediting anyone (refunded, not ours)."""

    note: str = Field(min_length=1, max_length=256)


class UsdtReservationAdminOut(BaseModel):
    """A reservation as the admin sees it."""

    number: str
    merchant_id: str
    merchant_title: str | None
    amount: UsdAmount
    status: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None


class UsdtReservationPageOut(BaseModel):
    """A page of reservations, newest first."""

    items: list[UsdtReservationAdminOut]
    next_cursor: str | None


__all__ = [
    "UsdtCreditIn",
    "UsdtDepositIn",
    "UsdtDepositOut",
    "UsdtDepositsOut",
    "UsdtDismissIn",
    "UsdtIncomingOut",
    "UsdtIncomingPageOut",
    "UsdtMode",
    "UsdtReservationAdminOut",
    "UsdtReservationPageOut",
    "UsdtSettingsIn",
    "UsdtSettingsOut",
    "UsdtStatusOut",
]
