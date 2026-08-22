"""Pydantic DTOs for the ``fx`` HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
    """Admin toggle + optional typed rate for one quote."""

    use_manual: bool
    manual_rate: Decimal | None = None


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


__all__ = ["AdminRateOut", "AdminRatesOut", "RateOut", "RateSettingIn", "RatesOut"]
