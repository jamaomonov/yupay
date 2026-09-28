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

* **History audit** (daily, ``jobs/skins_history_audit.py``, spec §6.5): the last 14 days
  of trades *we* consider settled — released (5), or failed with the customer refunded — are
  read again from Waxpeer. It only alerts, never writes: a released trade that Waxpeer now
  shows as 6 (a late rollback), a refunded one Waxpeer shows as 4/5 (the skin went out and
  the money came back), or one Waxpeer has no record of. In-flight and accepted trades are
  left to the two sweeps above, so nothing is alerted twice.

The general ``waxpeer_reconcile`` sweep skips skin tasks: one owner per task.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerError,
    WaxpeerUnavailableError,
)
from yupay.modules.fulfillment.suppliers.waxpeer_skins import (
    SKIN_KIND,
    AmbiguousTradeError,
    mirror,
    pick_trade,
)
from yupay.modules.fulfillment.suppliers.waxpeer_trades import WaxpeerTrade
from yupay.modules.orders.models import OrderItem
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


AUDIT_DAYS = 14


def _divergence(row: SkinTrade, refunded: bool, trade: WaxpeerTrade | None) -> str | None:
    """What is wrong with a settled trade, in the alert's words; ``None`` when Waxpeer agrees."""
    if trade is None:
        # A row that never reached Waxpeer (status None: sold out before any buy) is fine.
        return "Waxpeer не знает сделку" if row.status is not None else None
    if not refunded and trade.status == 6:
        return f"откат после выпуска; штраф: {trade.penalties or '—'}"
    if refunded and trade.status in (4, 5):
        return f"скин ушёл (статус {trade.status}), а деньги вернули"
    return None


async def _settled_rows(db: AsyncSession, days: int) -> list[tuple[SkinTrade, str, bool]]:
    rows = await db.execute(
        select(SkinTrade, OrderItem.order_id, OrderItem.fulfillment_state)
        .join(OrderItem, OrderItem.id == SkinTrade.order_item_id)
        .where(
            SkinTrade.created_at >= now() - timedelta(days=days),
            or_(
                SkinTrade.status.in_((5, 6)),
                SkinTrade.is_released.is_(True),
                OrderItem.fulfillment_state == "failed",
            ),
        )
        .order_by(SkinTrade.created_at, SkinTrade.id)
    )
    return [
        (row, str(order_id), row.status == 6 or state == "failed")
        for row, order_id, state in rows.all()
    ]


async def audit_recent_trades(
    db: AsyncSession,
    client: TradeLookup,
    *,
    alert: Callable[[str], Awaitable[None]],
    days: int = AUDIT_DAYS,
) -> int:
    """Compare the last ``days`` of settled trades with Waxpeer; alert on each divergence.

    Read-only: the fast sweep and the protection watch own every state change.

    Args:
        db: Active session.
        client: Waxpeer lookup by our ``project_id`` (batches of 100).
        alert: Sends one ops alert.
        days: How far back to look.

    Returns:
        How many divergences were alerted; 0 when Waxpeer could not be read.
    """
    rows = await _settled_rows(db, days)
    found: list[WaxpeerTrade] = []
    try:
        for start in range(0, len(rows), _BATCH):
            chunk = rows[start : start + _BATCH]
            found += await client.check_project_ids([r.project_id for r, _, _ in chunk])
    except (WaxpeerError, WaxpeerUnavailableError) as exc:
        log.warning("skins.audit.unavailable", error=type(exc).__name__, trades=len(rows))
        return 0
    diverged = 0
    for row, order_id, refunded in rows:
        problem: str | None
        try:
            trade = pick_trade([t for t in found if t.project_id == row.project_id], row.waxpeer_id)
        except AmbiguousTradeError:
            trade, problem = None, "несколько живых сделок под одним ключом"
        else:
            problem = _divergence(row, refunded, trade)
        if problem is None:
            continue
        diverged += 1
        log.warning("skins.audit.divergence", project_id=row.project_id, order_id=order_id)
        await alert(
            "<b>Скин: расхождение с Waxpeer</b>\n"
            f"{row.market_hash_name} · заказ {order_id}\n"
            f"{problem}; у нас статус {row.status if row.status is not None else '—'}, "
            f"у Waxpeer {trade.status if trade is not None else '—'}"
        )
    log.info("skins.audit.done", trades=len(rows), diverged=diverged)
    return diverged


__all__ = [
    "AUDIT_DAYS",
    "BUYING_RECHECK_SECONDS",
    "SENT_RECHECK_SECONDS",
    "TradeLookup",
    "audit_recent_trades",
    "due_skin_task_ids",
    "skin_recheck_seconds",
    "skin_task_filter",
    "watch_protected_trades",
]
