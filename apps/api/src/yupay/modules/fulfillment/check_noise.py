"""Which status-check failures are noise, and for how long.

A status check reads; it never spends. When the supplier throttles it (429) or
cannot be reached (connect timeout, DNS), the task simply stays in flight and
the next poll asks again — 10 to 60 seconds later. Announcing each of those in
the ops chat buried the alerts that need a person: on 2026-11-17 one buyer's
36 FazerCards lines pushed the poll to their 120-a-minute ceiling and the chat
filled with «Слишком много запросов» and ``ConnectTimeout`` for orders that all
went on to be delivered.

So a transient failure on a status check is still written to the attempt log,
but it reaches the chat only once it has persisted for
:data:`QUIET_FOR` — the same error on the same task, uninterrupted. A supplier
that is really down still announces itself, five minutes later than before.

Scope is the panel vendors (NOVA, FazerCards), whose client separates "never
reached" and "throttled" from a real answer. Others keep alerting at once.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from yupay.modules.fulfillment.suppliers.panel_client import (
    PanelError,
    PanelUnavailableError,
)

#: How long one transient failure must last before it is announced.
QUIET_FOR: Final = timedelta(minutes=5)


def is_transient_check_failure(exc: BaseException) -> bool:
    """True for a failed status read that the next poll is likely to clear.

    Walks the cause chain because the adapters re-raise the client's error as a
    ``FulfillerError``.
    """
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, PanelUnavailableError):
            return True
        if isinstance(seen, PanelError) and seen.status == 429:
            return True
        seen = seen.__cause__
    return False


__all__ = ["QUIET_FOR", "is_transient_check_failure"]
