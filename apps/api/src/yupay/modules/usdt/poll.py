"""One poll of every watched chain: read new transfers, journal and credit them (ADR-0104).

Lives in the API package so the scheduler job stays a thin wrapper and the
logic is testable without APScheduler. Each chain is read on its own — one
chain's outage never holds back another — each transfer is its own
transaction, and no lock is held across a network call.

The cursor rules are what keep a transfer from being skipped:

- it only moves forward, and never past a transfer that failed to ingest;
- TRON (cursor = block time, ms): never past "now"; a normal poll re-reads
  ``OVERLAP`` before it, because TronGrid's confirmed index can lag; a read
  that hit the page cap resumes **exactly** where it stopped (``cursor_exact``)
  — with the overlap, a flood of spam rows inside ten minutes would be re-read
  every tick and nothing after it reached (security review 2026-11-11);
- EVM (cursor = last block read): only blocks ``confirmations`` deep are read,
  so the next poll starts at the following block with no overlap;
- a chain with no cursor (new address) starts at "now" / the confirmed head
  and reads nothing before it: that address's history is not top-ups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

import httpx
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.usdt import evm, tron
from yupay.modules.usdt.chain import Batch, ChainUnavailableError, Transfer
from yupay.modules.usdt.intake import DUST, ingest
from yupay.modules.usdt.models import UsdtIncoming, UsdtNetwork, UsdtReservation
from yupay.modules.usdt.networks import NETWORKS, Network
from yupay.modules.usdt.settings import load_networks, load_settings

log = get_logger("yupay.usdt.poll")

OVERLAP: Final = timedelta(minutes=10)


@dataclass
class PollResult:
    """Counts for one poll of every chain, and the alerts to send after the commits."""

    seen: int = 0
    matched: int = 0
    unmatched: int = 0
    failed: bool = False
    truncated: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    alerts: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class _Target:
    net: Network
    address: str
    cursor: int | None
    exact: bool


def _rpc_url(net: Network) -> str:
    s = get_settings()
    return s.bsc_rpc_url if net.code == "bep20" else s.eth_rpc_url


async def _targets(sessions: async_sessionmaker[AsyncSession]) -> list[_Target]:
    """The chains to read now.

    A chain switched off — or the whole method — is still read while any of
    its reservations holds an amount: a reseller who already sent must be
    credited even if the switch was flipped behind them.
    """
    async with sessions() as db:
        s = await load_settings(db)
        rows = await load_networks(db)
        holding = set(
            (
                await db.execute(
                    select(UsdtReservation.network)
                    .where(UsdtReservation.holds_amount.is_(True))
                    .distinct()
                )
            ).scalars()
        )
        await db.commit()
    out: list[_Target] = []
    for r in rows:
        live = s.mode != "off" and r.enabled
        if r.address and (live or r.network in holding):
            out.append(_Target(NETWORKS[r.network], r.address, r.cursor, r.cursor_exact))
    return out


async def _known(
    sessions: async_sessionmaker[AsyncSession], transfers: list[Transfer]
) -> set[tuple[str, str, str]]:
    """Events of this batch already journaled — re-reads would fail their INSERT."""
    ids = list({t.tx_id for t in transfers})
    if not ids:
        return set()
    async with sessions() as db:
        rows = await db.execute(
            select(UsdtIncoming.network, UsdtIncoming.tx_id, UsdtIncoming.event_key).where(
                UsdtIncoming.tx_id.in_(ids)
            )
        )
    return {(n, tx, key) for n, tx, key in rows.all()}


async def _ingest_all(
    sessions: async_sessionmaker[AsyncSession],
    transfers: list[Transfer],
    now_: datetime,
    result: PollResult,
) -> Transfer | None:
    """Ingest in order into ``result``; stop at the first failure and return that transfer."""
    known = await _known(sessions, transfers)
    for t in transfers:
        if t.amount < DUST or (t.network, t.tx_id, t.event_key) in known:
            continue
        try:
            async with sessions() as db:
                out = await ingest(db, t, received_at=now_)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - reported by class; the cursor stays put
            log.error(  # noqa: TRY400
                "usdt.ingest_failed", network=t.network, tx_id=t.tx_id, error=type(exc).__name__
            )
            result.failed = True
            result.alerts.append(
                (
                    "usdt_ingest_failed",
                    f"USDT ({t.network.upper()}): не удалось обработать перевод {t.tx_id} — "
                    "зачисление по этой сети остановлено на нём, нужен разбор",
                )
            )
            return t
        result.seen += out.status != "duplicate"
        result.matched += out.status == "matched"
        result.unmatched += out.status == "unmatched"
        result.alerts.extend(out.alerts)
    return None


def _next_cursor(
    target: _Target, batch: Batch, failed: Transfer | None, now_ms: int
) -> tuple[int, bool]:
    """Where this chain's next poll starts, and whether it skips the TRON overlap."""
    cursor = target.cursor or 0
    if target.net.kind == "evm":
        if failed is not None:
            return max(cursor, failed.position - 1), False
        return max(cursor, batch.last_position or cursor), False
    if failed is not None:
        # With the overlap: the failed transfer (and anything after it) is read again.
        return max(cursor, min(failed.position, now_ms)), False
    return max(cursor, min(batch.last_position or cursor, now_ms)), batch.truncated


async def _start_cursor(target: _Target, now_ms: int, http: httpx.AsyncClient | None) -> int:
    if target.net.kind == "tron":
        return now_ms
    return await evm.chain_head(target.net, url=_rpc_url(target.net), http=http)


async def _fetch(target: _Target, http: httpx.AsyncClient | None) -> Batch:
    cursor = target.cursor or 0
    if target.net.kind == "tron":
        overlap = 0 if target.exact else int(OVERLAP.total_seconds() * 1000)
        return await tron.fetch_transfers(
            target.address, min_block_ms=max(0, cursor - overlap), http=http
        )
    return await evm.fetch_transfers(
        target.net, target.address, after_block=cursor, url=_rpc_url(target.net), http=http
    )


async def _save_cursor(
    sessions: async_sessionmaker[AsyncSession], target: _Target, cursor: int, exact: bool
) -> None:
    async with sessions() as db:
        row = await db.get(UsdtNetwork, target.net.code, with_for_update=True)
        # Only for the address we read, and only forward: an admin may have
        # changed the address (which clears the cursor) while we were reading.
        if (
            row is not None
            and row.address == target.address
            and (row.cursor is None or row.cursor <= cursor)
        ):
            row.cursor, row.cursor_exact = cursor, exact
        await db.commit()


async def _poll_chain(
    sessions: async_sessionmaker[AsyncSession],
    target: _Target,
    now_: datetime,
    http: httpx.AsyncClient | None,
    result: PollResult,
) -> None:
    now_ms = int(now_.timestamp() * 1000)
    try:
        if target.cursor is None:
            start = await _start_cursor(target, now_ms, http)
            await _save_cursor(sessions, target, start, target.net.kind == "tron")
            return
        batch = await _fetch(target, http)
    except ChainUnavailableError as exc:
        log.warning("usdt.chain_unavailable", network=target.net.code, reason=str(exc))
        result.unavailable.append(target.net.code)
        return
    failed = await _ingest_all(sessions, batch.transfers, now_, result)
    cursor, exact = _next_cursor(target, batch, failed, now_ms)
    await _save_cursor(sessions, target, cursor, exact)
    if batch.truncated:
        result.truncated.append(target.net.code)
        log.warning("usdt.poll_truncated", network=target.net.code)


async def poll_once(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now_: datetime,
    http: httpx.AsyncClient | None = None,
) -> PollResult:
    """Read every watched chain once. Never raises for a chain being down.

    A chain whose API failed is listed in ``unavailable``; the others are read
    as usual.
    """
    result = PollResult()
    for target in await _targets(sessions):
        await _poll_chain(sessions, target, now_, http, result)
    if result.seen:
        log.info("usdt.poll", seen=result.seen, matched=result.matched, unmatched=result.unmatched)
    return result


async def waiting(sessions: async_sessionmaker[AsyncSession]) -> bool:
    """Whether any reservation still holds an amount (someone may be waiting)."""
    async with sessions() as db:
        return bool(await db.scalar(select(exists().where(UsdtReservation.holds_amount.is_(True)))))


__all__ = ["OVERLAP", "PollResult", "poll_once", "waiting"]
