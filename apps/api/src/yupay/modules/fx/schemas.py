"""Pydantic DTOs for the ``fx`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RateOut(BaseModel):
    """A single rate as returned by ``GET /api/v1/fx/rates``."""

    model_config = ConfigDict(from_attributes=True)

    base: str
    quote: str
    rate: Decimal
    fetched_at: datetime
    source: str


class RatesOut(BaseModel):
    """List of supported rates for the storefront."""

    base: str
    rates: list[RateOut]


class RateSettingIn(BaseModel):
    """Admin toggle + optional typed rate for one quote.

    Bounded at the edge as well as in the service: the column is
    ``Numeric(20, 10)``, so an unbounded Decimal reaches Postgres as a 500
    rather than a 422, and a pinned rate skips the pricing band by design
    (ADR-0055) — this field deserves what checking it can get. The admin UI
    asks for confirmation when the number is far from the live FX rate.
    """

    use_manual: bool
    manual_rate: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=10)


class AdminRateOut(RateOut):
    """Effective rate plus the live FX and the admin override fields."""

    use_manual: bool
    manual_rate: Decimal | None
    fx_rate: Decimal | None
    fx_source: str | None
    fx_fetched_at: datetime | None


class AdminRatesOut(BaseModel):
    """Admin listing: effective rate, live FX, and the per-quote toggle."""

    base: str
    rates: list[AdminRateOut]


class ProviderQuoteOut(BaseModel):
    """One provider's attempt at one quote."""

    quote: str
    rate: Decimal | None
    error: str | None = None


class ProviderChainItemOut(BaseModel):
    """One adapter in the admin chain, with live probes."""

    slug: str
    title: str
    kind: str
    enabled: bool
    configured: bool
    role: str
    sort_order: int
    quotes: list[ProviderQuoteOut]


class ProviderChainOut(BaseModel):
    """Full admin view of every FX adapter."""

    quotes: list[str]
    items: list[ProviderChainItemOut]


class ProviderChainItemIn(BaseModel):
    """Reorder/enable one adapter."""

    slug: str
    enabled: bool


class ProviderChainIn(BaseModel):
    """Replace the whole chain. Must list every known slug once."""

    items: list[ProviderChainItemIn]


__all__ = [
    "AdminRateOut",
    "AdminRatesOut",
    "ProviderChainIn",
    "ProviderChainItemIn",
    "ProviderChainItemOut",
    "ProviderChainOut",
    "ProviderQuoteOut",
    "RateOut",
    "RateSettingIn",
    "RatesOut",
]
