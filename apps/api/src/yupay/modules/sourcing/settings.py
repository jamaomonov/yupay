"""Read and edit the smart-sourcing switches (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.sourcing.models import SourcingSettings

FailoverMode = Literal["off", "retail", "all"]
SmartMode = Literal["off", "shadow", "on"]
_ROW_ID = 1


class SourcingSettingsOut(BaseModel):
    """The switches as the admin reads them."""

    model_config = ConfigDict(from_attributes=True)

    failover_mode: FailoverMode
    failover_min_margin_retail_pct: Decimal
    failover_min_margin_b2b_pct: Decimal
    failover_max_step_pct: Decimal
    smart_mode: SmartMode
    smart_switch_pct: Decimal
    smart_dwell_hours: int
    smart_stock_step_pct: Decimal


class SourcingSettingsPatch(BaseModel):
    """A partial edit; a field left out keeps its value."""

    model_config = ConfigDict(extra="forbid")

    failover_mode: FailoverMode | None = None
    failover_min_margin_retail_pct: Decimal | None = Field(default=None, ge=0, le=50)
    failover_min_margin_b2b_pct: Decimal | None = Field(default=None, ge=0, le=50)
    failover_max_step_pct: Decimal | None = Field(default=None, ge=0, le=50)
    smart_mode: SmartMode | None = None
    smart_switch_pct: Decimal | None = Field(default=None, ge=0, le=50)
    smart_dwell_hours: int | None = Field(default=None, ge=0, le=168)
    smart_stock_step_pct: Decimal | None = Field(default=None, ge=0, le=50)


async def load(db: AsyncSession) -> SourcingSettings:
    """The settings row; an unsaved default (failover off) when it is missing."""
    row = (
        await db.execute(select(SourcingSettings).where(SourcingSettings.id == _ROW_ID))
    ).scalar_one_or_none()
    if row is not None:
        return row
    return SourcingSettings(
        id=_ROW_ID,
        failover_mode="off",
        failover_min_margin_retail_pct=Decimal("3"),
        failover_min_margin_b2b_pct=Decimal("0"),
        failover_max_step_pct=Decimal("6"),
        smart_mode="off",
        smart_switch_pct=Decimal("1"),
        smart_dwell_hours=6,
        smart_stock_step_pct=Decimal("6"),
    )


async def update(
    db: AsyncSession, patch: SourcingSettingsPatch, *, admin_id: str
) -> SourcingSettings:
    """Apply ``patch`` to the row (creating it if missing) and return it."""
    row = (
        await db.execute(
            select(SourcingSettings).where(SourcingSettings.id == _ROW_ID).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = await load(db)
        db.add(row)
    for field, value in patch.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    row.updated_by = admin_id
    row.updated_at = now()
    await db.flush()
    return row


__all__ = [
    "FailoverMode",
    "SmartMode",
    "SourcingSettingsOut",
    "SourcingSettingsPatch",
    "load",
    "update",
]
