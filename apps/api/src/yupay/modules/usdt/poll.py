"""One poll of the chain: read new transfers, journal and credit them (ADR-0104).

Lives in the API package so the scheduler job stays a thin wrapper and the
logic is testable without APScheduler. Each transfer is its own transaction,
and no lock is held across the TronGrid call — the fetch happens before any
session work.

The cursor rules are what keep a transfer from being skipped:

- it only moves forward, never past "now", and never past a transfer that
  failed to ingest;
- a normal poll re-reads ``OVERLAP`` before it, because TronGrid's confirmed
  index can lag and the journal's unique event key makes the overlap free;
- a poll that hit the page cap resumes **exactly** where it stopped
  (``cursor_exact``). With the overlap, 5 000 zero-value spam transfers inside
  ten minutes would be re-read every tick and nothing after them reached
  (security review 2026-11-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

import httpx
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.logging import get_logger
from yupay.modules.usdt.intake import DUST, ingest
from yupay.modules.usdt.models import UsdtIncoming, UsdtReservation
from yupay.modules.usdt.settings import load_settings
from yupay.modules.usdt.tron import Batch, Transfer, fetch_transfers

log = get_logger("yupay.usdt.poll")

OVERLAP: Final = timedelta(minutes=10)


@dataclass
class PollResult:
    """Counts for one poll and the alerts to send after the commits."""

    seen: int = 0
    matched: int = 0
    unmatched: int = 0
    failed: bool = False
    truncated: bool = False
    alerts: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class _Target:
    address: str
    cursor: int
    exact: bool


async def _target(sessions: async_sessionmaker[AsyncSession]) -> _Target | None:
    """What to read, or ``None`` when there is nothing to watch.

    ``mode = off`` still polls while any reservation holds an amount: a
    reseller who already sent must be credited even if the method was
    switched off behind them.
    """
    async with sessions() as db:
        s = await load_settings(db)
        waiting = await db.scalar(select(exists().where(UsdtReservation.holds_amount.is_(True))))
        await db.commit()
    if not s.address or s.cursor_block_ms is None:
        return None
    if s.mode == "off" and not waiting:
        return None
    return _Target(s.address, s.cursor_block_ms, s.cursor_exact)


async def _known(
    sessions: async_sessionmaker[AsyncSession], transfers: list[Transfer]
) -> set[tuple[str, str, Decimal]]:
    """Events of this batch already journaled — the overlap re-reads them every tick.

    Skipping them here spares a failed INSERT per event per tick; the unique
    key in ``ingest`` stays the guarantee.
    """
    ids = list({t.tx_id for t in transfers})
    if not ids:
        return set()
    async with sessions() as db:
        rows = await db.execute(
            select(UsdtIncoming.tx_id, UsdtIncoming.from_address, UsdtIncoming.amount_usdt).where(
                UsdtIncoming.tx_id.in_(ids)
            )
        )
    return {(tx, sender, amount) for tx, sender, amount in rows.all()}


async def _ingest_all(
    sessions: async_sessionmaker[AsyncSession], transfers: list[Transfer], now_: datetime
) -> tuple[PollResult, int | None]:
    """Ingest in order; stop at the first failure. Returns the last block fully done."""
    result = PollResult()
    done: int | None = None
    known = await _known(sessions, transfers)
    for t in transfers:
        if t.amount >= DUST and (t.tx_id, t.from_address, t.amount) not in known:
            try:
                async with sessions() as db:
                    out = await ingest(db, t, received_at=now_)
                    await db.commit()
            except Exception as exc:  # noqa: BLE001 - reported by class; the cursor stays put
                log.error("usdt.ingest_failed", tx_id=t.tx_id, error=type(exc).__name__)  # noqa: TRY400
                result.failed = True
                result.alerts.append(
                    (
                        "usdt_ingest_failed",
                        f"USDT: не удалось обработать перевод {t.tx_id} — зачисление "
                        "остановлено на нём, нужен разбор (usdt.ingest_failed в логах)",
                    )
                )
                return result, done
            result.seen += out.status != "duplicate"
            result.matched += out.status == "matched"
            result.unmatched += out.status == "unmatched"
            result.alerts.extend(out.alerts)
        done = t.block_ms
    return result, done


def _next_cursor(
    batch: Batch, result: PollResult, done: int | None, cursor: int, now_ms: int
) -> tuple[int, bool]:
    """Where the next poll starts, and whether it skips the overlap."""
    if result.failed:
        # Up to the last transfer fully ingested, and with the overlap: the
        # failed one (and anything after it) is read again.
        return max(cursor, min(done or cursor, now_ms)), False
    newest = max(cursor, min(batch.last_block_ms or cursor, now_ms))
    return newest, batch.truncated


async def poll_once(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now_: datetime,
    http: httpx.AsyncClient | None = None,
) -> PollResult:
    """Fetch transfers since the cursor, ingest each, then advance the cursor.

    Raises:
        TronUnavailableError: TronGrid failed; nothing was written.
    """
    target = await _target(sessions)
    if target is None:
        return PollResult()
    overlap_ms = 0 if target.exact else int(OVERLAP.total_seconds() * 1000)
    batch = await fetch_transfers(
        target.address, min_block_ms=max(0, target.cursor - overlap_ms), http=http
    )
    result, done = await _ingest_all(sessions, batch.transfers, now_)
    result.truncated = batch.truncated
    cursor, exact = _next_cursor(batch, result, done, target.cursor, int(now_.timestamp() * 1000))
    async with sessions() as db:
        s = await load_settings(db)
        # Only for the address we read: an admin may have changed it meanwhile.
        if s.address == target.address and (s.cursor_block_ms or 0) <= cursor:
            s.cursor_block_ms, s.cursor_exact = cursor, exact
        await db.commit()
    if batch.truncated:
        log.warning("usdt.poll_truncated", last_block_ms=batch.last_block_ms)
    if result.seen:
        log.info("usdt.poll", seen=result.seen, matched=result.matched, unmatched=result.unmatched)
    return result


__all__ = ["OVERLAP", "PollResult", "poll_once"]
