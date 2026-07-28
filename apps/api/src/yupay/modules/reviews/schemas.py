"""Pydantic v2 request/response models for the reviews module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_BODY_MAX = 2000
_REASON_MAX = 64


class ReviewCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    brand_slug: str = Field(..., min_length=1, max_length=64)
    rating: int = Field(..., ge=1, le=5)
    body: str | None = Field(default=None, max_length=_BODY_MAX)


class ReviewOut(BaseModel):
    """A published review as shown on the public brand page.

    ``author_name`` is the reviewer's ``display_name`` or ``None`` — never the
    email. The frontend localizes a generic label when it is ``None``.
    """

    id: str
    rating: int
    body: str | None
    author_name: str | None
    created_at: datetime


class ReviewStatsOut(BaseModel):
    avg: float
    count: int
    dist: dict[int, int]


class ReviewListOut(BaseModel):
    items: list[ReviewOut]
    next_cursor: str | None
    stats: ReviewStatsOut


class OwnReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    brand_id: str
    rating: int


class OwnReviewListOut(BaseModel):
    items: list[OwnReviewOut]


class ReviewReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=_REASON_MAX)


class AdminReviewOut(BaseModel):
    id: str
    brand_id: str
    user_id: str
    order_id: str
    rating: int
    body: str | None
    status: str
    report_count: int
    created_at: datetime


class AdminReviewListOut(BaseModel):
    items: list[AdminReviewOut]
    total: int


__all__ = [
    "AdminReviewListOut",
    "AdminReviewOut",
    "OwnReviewListOut",
    "OwnReviewOut",
    "ReviewCreateIn",
    "ReviewListOut",
    "ReviewOut",
    "ReviewReportIn",
    "ReviewStatsOut",
]
