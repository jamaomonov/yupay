"""Wire shapes for the cabinet's P2P top-up routes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from yupay.modules.merchants.machine_schemas import UsdAmount


class P2PDepositIn(BaseModel):
    """Request to reserve an amount, in whole soʻm."""

    amount_uzs: int = Field(gt=0, le=1_000_000_000)


class P2PCardDetailsOut(BaseModel):
    """Where to send the transfer. Present only while the top-up is pending."""

    pan: str = Field(description="Full card number grouped in fours")
    holder_name: str
    network: str


class P2PDepositOut(BaseModel):
    """One top-up reservation."""

    number: str
    status: str
    amount_uzs: int
    amount_usd: UsdAmount
    fx_rate: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    card: P2PCardDetailsOut | None


class P2PDepositsOut(BaseModel):
    """A page of top-ups, newest first; items never carry the card."""

    items: list[P2PDepositOut]
    next_cursor: str | None


class P2PStatusOut(BaseModel):
    """Whether the cabinet should offer top-up, and the rate to preview it at."""

    enabled: bool
    fx_rate: str | None


# --- admin -----------------------------------------------------------------

P2PMode = Literal["off", "allowlist", "all"]
P2PNetwork = Literal["humo", "uzcard"]


class P2PSettingsOut(BaseModel):
    """The P2P switch row."""

    mode: P2PMode
    allowlist_merchant_ids: list[str]
    humo_bot_user_id: int | None
    owner_telegram_user_id: int | None
    business_connection_id: str | None = Field(
        description="Read-only: the owner's Telegram Business connection, captured on connect."
    )
    updated_at: datetime


class P2PSettingsIn(BaseModel):
    """Partial update of the switch row; absent fields are left alone."""

    mode: P2PMode | None = None
    allowlist_merchant_ids: list[str] | None = None
    humo_bot_user_id: int | None = None
    owner_telegram_user_id: int | None = None


class P2PCardAdminOut(BaseModel):
    """A card as the admin sees it. The full number is never part of it."""

    id: str
    label: str
    pan_last4: str
    holder_name: str
    network: str
    active: bool
    min_amount_uzs: int
    max_amount_uzs: int
    daily_limit_uzs: int | None
    matched_today_uzs: int
    last_incoming_at: datetime | None
    chain_ok_last: bool | None


class P2PCardCreateIn(BaseModel):
    """A new card. ``pan`` is write-only."""

    label: str = Field(min_length=1, max_length=64)
    pan: str = Field(min_length=16, max_length=32)
    holder_name: str = Field(min_length=1, max_length=128)
    network: P2PNetwork
    min_amount_uzs: int = Field(default=10_000, gt=0)
    max_amount_uzs: int = Field(default=10_000_000, gt=0)
    daily_limit_uzs: int | None = Field(default=None, gt=0)
    active: bool = True


class P2PCardPatchIn(BaseModel):
    """Partial card update; ``pan`` re-seals the number."""

    label: str | None = Field(default=None, min_length=1, max_length=64)
    pan: str | None = Field(default=None, min_length=16, max_length=32)
    holder_name: str | None = Field(default=None, min_length=1, max_length=128)
    network: P2PNetwork | None = None
    min_amount_uzs: int | None = Field(default=None, gt=0)
    max_amount_uzs: int | None = Field(default=None, gt=0)
    daily_limit_uzs: int | None = Field(default=None, gt=0)
    active: bool | None = None


class P2PIncomingReservationOut(BaseModel):
    """The reservation a transfer was credited to."""

    number: str
    merchant_id: str | None
    merchant_title: str | None
    amount_usd: UsdAmount


class P2PIncomingOut(BaseModel):
    """One journal row. The raw notification text is only on the detail."""

    id: str
    received_at: datetime
    bank_time: datetime | None
    kind: str
    amount_uzs: Decimal | None
    source_text: str | None
    card_last4: str | None
    balance_after: Decimal | None
    chain_ok: bool | None
    result: str
    reservation: P2PIncomingReservationOut | None = None


class P2PIncomingDetailOut(P2PIncomingOut):
    """A journal row with the notification text, which is PII."""

    raw_text: str


class P2PIncomingPageOut(BaseModel):
    """A page of the journal, newest first."""

    items: list[P2PIncomingOut]
    next_cursor: str | None


class P2PReservationAdminOut(BaseModel):
    """One reservation as support sees it."""

    number: str
    merchant_id: str | None
    merchant_title: str | None
    card_last4: str
    amount_uzs: int
    amount_usd: UsdAmount
    status: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None


class P2PReservationPageOut(BaseModel):
    """A page of reservations, newest first."""

    items: list[P2PReservationAdminOut]
    next_cursor: str | None
