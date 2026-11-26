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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


#: SKUs whose supplier refusals are routine, not incidents. Free Fire's Level
#: Up Packages are refused whenever the account's level is out of the pack's
#: range: 118 of them in three days on 2026-11-26, every one refunded on its
#: own, and the chat was all of them (owner's call). Matched as a substring of
#: ``sku_code``: ``freefire_cis-level-up-6`` … ``-30``.
QUIET_FAILURE_SKU_MARKERS: Final = ("-level-up-",)


def is_quiet_failure_sku(sku_code: str | None) -> bool:
    """True when a supplier's refusal of this SKU is not announced in the chat."""
    if not sku_code:
        return False
    return any(m in sku_code for m in QUIET_FAILURE_SKU_MARKERS)


async def task_sku_is_quiet(db: AsyncSession, order_item_id: str) -> bool:
    """:func:`is_quiet_failure_sku` for a task's line."""
    from yupay.modules.catalog.models import Sku
    from yupay.modules.orders.models import OrderItem

    code = (
        await db.execute(
            select(Sku.sku_code)
            .join(OrderItem, OrderItem.sku_id == Sku.id)
            .where(OrderItem.id == order_item_id)
        )
    ).scalar_one_or_none()
    return is_quiet_failure_sku(code)


__all__ = [
    "QUIET_FAILURE_SKU_MARKERS",
    "QUIET_FOR",
    "is_quiet_failure_sku",
    "is_transient_check_failure",
    "task_sku_is_quiet",
]
