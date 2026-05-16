"""Outbox relay — pulls unpublished events from PG and dispatches them to Dramatiq.

Implementation lives here as a stub interface; the concrete actor wiring will be added
when the first event-producing module lands. The contract is documented for clarity.
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
