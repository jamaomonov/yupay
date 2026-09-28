"""What the scheduler's two skin sweeps do (plan 3a, Task 6).

* **Fast sweep** (every 5 s, ``jobs/skins_trades_reconcile.py``): the in-flight skin
  tasks whose check is due, each run through ``process_webhook_update`` like every other
  supplier; the next check is 5 s away while Waxpeer is still buying (status 0–2) and
  10 s once the offer is sent — the customer is waiting on the next step.
* **Protection watch** (hourly, ``jobs/skins_protection_watch.py``): trades already
  accepted (status 4 with ``release_date``) are followed through Steam's 7-day
  protection. Released (5) closes the row; a rollback (6 with ``penalties``) is money we
  lost after delivery — the customer keeps nothing to refund, ops gets an alert and the
  task carries ``skin_rollback`` for the books.

The general ``waxpeer_reconcile`` sweep skips skin tasks: one owner per task.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.waxpeer_skins import (
    SKIN_KIND,
    AmbiguousTradeError,
    mirror,
    pick_trade,
)
from yupay.modules.fulfillment.suppliers.waxpeer_trades import WaxpeerTrade
from yupay.modules.skins.models import SkinTrade

log = get_logger("yupay.fulfillment.skin_sweeps")

BUYING_RECHECK_SECONDS = 5
SENT_RECHECK_SECONDS = 10
_BATCH = 100


class TradeLookup(Protocol):
    """``WaxpeerTradeClient.check_project_ids``."""

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """Trades by our ``project_id``."""
        ...


def skin_task_filter() -> object:
    """SQL predicate: the task is a skin purchase."""
    return FulfillmentTask.extra_metadata["waxpeer_kind"].astext == SKIN_KIND


async def due_skin_task_ids(db: AsyncSession, *, limit: int = 500) -> list[str]:
    """In-flight skin tasks whose next status check is due (or never happened)."""
    rows = await db.execute(
        select(FulfillmentTask.id)
        .where(
            FulfillmentTask.supplier == "waxpeer",
            FulfillmentTask.status == "in_progress",
            skin_task_filter(),  # type: ignore[arg-type] # a SQL boolean expression
            or_(
                FulfillmentTask.next_attempt_at.is_(None),
                FulfillmentTask.next_attempt_at <= now(),
            ),
        )
        .order_by(FulfillmentTask.created_at, FulfillmentTask.id)
        .limit(limit)
    )
    return [str(r) for r in rows.scalars().all()]


async def skin_recheck_seconds(db: AsyncSession, *, task_id: str) -> int:
    """5 s while Waxpeer is buying, 10 s once the offer is out."""
    status = (
        await db.execute(select(SkinTrade.status).where(SkinTrade.task_id == task_id))
    ).scalar_one_or_none()
    return SENT_RECHECK_SECONDS if status is not None and status >= 4 else BUYING_RECHECK_SECONDS


async def watch_protected_trades(
    db: AsyncSession,
    client: TradeLookup,
    *,
    alert: Callable[[str], Awaitable[None]],
) -> int:
    """Refresh accepted, not-yet-released trades; returns how many were looked at."""
    rows = list(
        (
            await db.execute(
                select(SkinTrade).where(
                    SkinTrade.status == 4,
                    SkinTrade.release_date.is_not(None),
                    SkinTrade.is_released.is_(False),
                )
            )
        ).scalars()
    )
    for start in range(0, len(rows), _BATCH):
        chunk = rows[start : start + _BATCH]
        found = await client.check_project_ids([r.project_id for r in chunk])
        for row in chunk:
            # Ours by Waxpeer's id: a refused attempt under the same key is not a rollback.
            try:
                trade = pick_trade(
                    [t for t in found if t.project_id == row.project_id], row.waxpeer_id
                )
            except AmbiguousTradeError:
                log.warning("skins.trade.ambiguous", project_id=row.project_id)
                continue
            if trade is None:
                continue
            mirror(row, trade)
            if trade.status == 6:
                await _rolled_back(db, row, trade, alert=alert)
    await db.commit()
    return len(rows)


async def _rolled_back(
    db: AsyncSession,
    row: SkinTrade,
    trade: WaxpeerTrade,
    *,
    alert: Callable[[str], Awaitable[None]],
) -> None:
    if row.task_id is not None:
        task = await db.get(FulfillmentTask, row.task_id)
        if task is not None:
            task.extra_metadata = {
                **(task.extra_metadata or {}),
                "skin_rollback": {
                    "at": now().isoformat(),
                    "reason": trade.reason,
                    "penalties": trade.penalties,
                },
            }
    log.warning(
        "skins.trade.rolled_back", project_id=row.project_id, has_penalties=bool(trade.penalties)
    )
    await alert(
        "<b>Скин: откат обмена после доставки</b>\n"
        f"{row.market_hash_name} · trade {row.trade_id or '—'}\n"
        f"причина: {trade.reason or '—'}; штраф: {trade.penalties or '—'}"
    )


__all__ = [
    "BUYING_RECHECK_SECONDS",
    "SENT_RECHECK_SECONDS",
    "TradeLookup",
    "due_skin_task_ids",
    "skin_recheck_seconds",
    "skin_task_filter",
    "watch_protected_trades",
]
