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


__all__ = ["RateOut", "RatesOut"]
