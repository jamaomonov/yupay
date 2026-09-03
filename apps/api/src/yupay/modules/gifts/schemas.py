"""Pydantic DTOs for the ``gifts`` admin HTTP surface."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class GiftsAdminSettingsOut(BaseModel):
    """Current Steam Gifts settings, as shown on the admin settings page."""

    margin_percent: Decimal
    enabled: bool
    region_default: str
    regions: list[str]


class GiftsSettingsIn(BaseModel):
    """Admin edit of the margin percent.

    Bounded at the edge as well as in the column (``Numeric(10, 4)``,
    ``CHECK margin_percent >= 0``): 0-100 is the only range that makes sense
    for a percentage margin, and an unbounded ``Decimal`` would otherwise
    reach Postgres as a 500 rather than a 422 — same reasoning as
    ``fx.schemas.RateSettingIn.manual_rate``.
    """

    margin_percent: Decimal = Field(ge=0, le=100, max_digits=10, decimal_places=4)


__all__ = ["GiftsAdminSettingsOut", "GiftsSettingsIn"]
