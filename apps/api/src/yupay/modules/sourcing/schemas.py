"""Pydantic DTOs for the sourcing admin HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["auto", "force_inventory", "force_supplier"]


class SourcingRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    supplier_slug: str | None = Field(default=None, min_length=2, max_length=32)


class SourcingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: str
    mode: Mode
    supplier_slug: str | None
    updated_by: str | None
    updated_at: datetime


class SourcingRuleListOut(BaseModel):
    items: list[SourcingRuleOut]


class SourcingDecisionOut(BaseModel):
    primary: str
    fallback: str | None
    strict: bool
    rule_present: bool


__all__ = [
    "Mode",
    "SourcingDecisionOut",
    "SourcingRuleIn",
    "SourcingRuleListOut",
    "SourcingRuleOut",
]
