"""Outbox relay — pulls unpublished events from PG and dispatches them.

Implementation lives here as a stub interface; nothing implements or calls it
today — no event-producing module has landed against it. The dispatch target
is undecided, not Dramatiq: `fulfillment`'s async path (ADR-0064) went
straight to `pg_notify` plus a Postgres-native queue instead of through this
generic outbox/relay abstraction. The contract stays documented for clarity.
"""

from __future__ import annotations

from typing import Protocol


class OutboxRelay(Protocol):
    """Contract every outbox relay implementation must satisfy."""

    async def tick(self) -> int:
        """Drain a batch of unpublished outbox rows.

        Returns:
            The number of messages dispatched in this tick.
        """
