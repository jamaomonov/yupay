"""Domain event base + in-process dispatcher.

The dispatcher is used in tests and for read-side projections that don't need the
durability of the outbox. Cross-module communication in production goes through the
outbox.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from yupay.core.clock import now
from yupay.core.ids import new_id


class DomainEvent(BaseModel):
    """Base class for all domain events. Immutable, serialisable, identified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=new_id)
    occurred_at: str = Field(default_factory=lambda: now().isoformat())
    type: str
    aggregate: str
    aggregate_id: str
    payload: dict[str, Any]


EventHandler = Callable[[DomainEvent], Awaitable[None]]
