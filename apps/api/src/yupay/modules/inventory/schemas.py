"""Pydantic DTOs for the inventory admin HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

CodeState = Literal["available", "reserved", "issued", "voided"]


class BulkUploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: str
    codes: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(
        min_length=1, max_length=5000
    )


class BulkUploadOut(BaseModel):
    upload_id: str
    total: int
    succeeded: int
    duplicates: int


class SkuCountsOut(BaseModel):
    sku_id: str
    available: int
    reserved: int
    issued: int
    voided: int


class CodeAdminOut(BaseModel):
    """Admin-only listing row. Includes the decrypted code."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    sku_id: str
    code: str
    state: CodeState
    order_item_id: str | None
    reserved_at: datetime | None
    issued_at: datetime | None
    voided_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class CodeAdminListOut(BaseModel):
    items: list[CodeAdminOut]


__all__ = [
    "BulkUploadIn",
    "BulkUploadOut",
    "CodeAdminListOut",
    "CodeAdminOut",
    "CodeState",
    "SkuCountsOut",
]
