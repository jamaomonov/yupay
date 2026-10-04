"""Wire shapes for the cabinet's P2P top-up routes."""

from __future__ import annotations

from datetime import datetime

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
