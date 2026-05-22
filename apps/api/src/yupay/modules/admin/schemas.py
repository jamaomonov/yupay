"""DTOs for admin-wide cross-cutting endpoints (search, customer-overview, …).

These schemas are intentionally generic: a single :class:`SearchHit` shape lets the admin SPA
render every result group with the same component while keeping per-type metadata in the
``sublabel`` field. See ADR-0017.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HitType = Literal["user", "order", "payment", "sku"]


class SearchHit(BaseModel):
    """One row in the search palette."""

    model_config = ConfigDict(frozen=True)

    type: HitType
    id: str
    label: str
    sublabel: str | None = None
    # Admin SPA deep-link path. Sprint-0 points users to ``/users/{id}``; once Customer 360
    # ships (Sprint 1) it will point to ``/customers/{id}``.
    path: str


class SearchOut(BaseModel):
    """Grouped search results — one bucket per source."""

    model_config = ConfigDict(frozen=True)

    users: list[SearchHit] = Field(default_factory=list)
    orders: list[SearchHit] = Field(default_factory=list)
    payments: list[SearchHit] = Field(default_factory=list)
    skus: list[SearchHit] = Field(default_factory=list)


__all__ = ["HitType", "SearchHit", "SearchOut"]
