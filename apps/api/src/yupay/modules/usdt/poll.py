"""One poll of the chain: read new transfers, journal and credit them (ADR-0104).

Lives in the API package so the scheduler job stays a thin wrapper and the
logic is testable without APScheduler. Each transfer is its own transaction:
one bad row never holds back the others, and no lock is held across the
TronGrid call — the fetch happens before any session work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.logging import get_logger
from yupay.modules.usdt.intake import ingest
from yupay.modules.usdt.settings import load_settings
from yupay.modules.usdt.tron import fetch_transfers

log = get_logger("yupay.usdt.poll")

#: Re-read this much before the cursor: TronGrid's confirmed index can lag,
#: and the journal's unique tx id makes the overlap free.
OVERLAP: Final = timedelta(minutes=10)


@dataclass
class PollResult:
    """Counts for one poll and the alerts to send after the commits."""

    seen: int = 0
    matched: int = 0
    unmatched: int = 0
    alerts: list[tuple[str, str]] = field(default_factory=list)


async def _target(sessions: async_sessionmaker[AsyncSession]) -> tuple[str, int] | None:
    async with sessions() as db:
        s = await load_settings(db)
        await db.commit()
        if s.mode == "off" or not s.address or s.cursor_block_ms is None:
            return None
        return s.address, s.cursor_block_ms


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
    result = PollResult()
    if target is None:
        return result
    address, cursor = target
    overlap_ms = int(OVERLAP.total_seconds() * 1000)
    transfers = await fetch_transfers(address, min_block_ms=max(0, cursor - overlap_ms), http=http)
    newest = cursor
    for t in transfers:
        async with sessions() as db:
            out = await ingest(db, t, received_at=now_)
            await db.commit()
        result.seen += out.status != "duplicate"
        result.matched += out.status == "matched"
        result.unmatched += out.status == "unmatched"
        result.alerts.extend(out.alerts)
        newest = max(newest, t.block_ms)
    if newest > cursor:
        async with sessions() as db:
            s = await load_settings(db)
            # Only move forward, and only for the address we read.
            if s.address == address and (s.cursor_block_ms or 0) < newest:
                s.cursor_block_ms = newest
            await db.commit()
    if result.seen:
        log.info("usdt.poll", seen=result.seen, matched=result.matched, unmatched=result.unmatched)
    return result


__all__ = ["OVERLAP", "PollResult", "poll_once"]
