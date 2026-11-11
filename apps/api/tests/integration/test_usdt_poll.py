"""USDT top-up: the TronGrid client and the poll's cursor rules (ADR-0104).

The cursor is what decides whether a transfer is ever read, so each rule the
2026-11-11 reviews found broken has a test here: the spam flood that stalled
it, the failure that silently stopped it, the future timestamp that skipped
ahead, and polling while the method is switched off.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.modules.merchants.deposit import deposit_balance
from yupay.modules.usdt import intake, poll
from yupay.modules.usdt.models import UsdtIncoming
from yupay.modules.usdt.settings import load_settings
from yupay.modules.usdt.tron import (
    USDT_CONTRACT,
    TronUnavailableError,
    fetch_transfers,
    parse_transfer,
)

from tests.integration.p2p_fixtures import _merchant
from tests.integration.usdt_fixtures import OURS, open_usdt, reserve, row, tron, units

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _paged(rows: list[dict[str, Any]], page: int = 200) -> Handler:
    """TronGrid's ``min_timestamp`` + ``fingerprint`` paging over ``rows`` (sorted)."""

    def handler(request: httpx.Request) -> httpx.Response:
        since = int(request.url.params["min_timestamp"])
        start = int(request.url.params.get("fingerprint", "0"))
        pool = [r for r in rows if r["block_timestamp"] >= since]
        chunk = pool[start : start + page]
        meta = {"fingerprint": str(start + page)} if start + page < len(pool) else {}
        return httpx.Response(200, json={"success": True, "data": chunk, "meta": meta})

    return handler


# --- parsing and the client --------------------------------------------------------


def test_parse_keeps_only_real_usdt_to_us() -> None:
    good = parse_transfer(row("100000000"), OURS)
    assert good is not None
    assert good.amount == Decimal("100")
    fake = row("100000000", token_info={"address": tron(9), "decimals": 6, "symbol": "USDT"})
    assert parse_transfer(fake, OURS) is None
    assert parse_transfer(row("100000000", to=tron(3)), OURS) is None
    assert parse_transfer(row("100000000", type="Approval"), OURS) is None
    assert parse_transfer(row("1e9"), OURS) is None
    assert parse_transfer(row("²"), OURS) is None  # isdigit() alone accepts it
    assert parse_transfer(row("0"), OURS) is None  # transferFrom(x, us, 0) poisoning
    assert parse_transfer(row("100", block_timestamp=True), OURS) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={}),
        httpx.Response(200, text="<html>cloudflare</html>"),
        httpx.Response(200, json={"success": False, "error": "rate limit"}),
        httpx.Response(200, json={"data": "nope"}),
    ],
)
async def test_any_unusable_answer_is_tron_unavailable(response: httpx.Response) -> None:
    async with _client(lambda _r: response) as http:
        with pytest.raises(TronUnavailableError):
            await fetch_transfers(OURS, min_block_ms=0, http=http)


@pytest.mark.asyncio
async def test_a_transport_error_is_tron_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _client(boom) as http:
        with pytest.raises(TronUnavailableError):
            await fetch_transfers(OURS, min_block_ms=0, http=http)


@pytest.mark.asyncio
async def test_the_query_names_the_contract_and_confirmed_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True, "data": [], "meta": {}})

    async with _client(handler) as http:
        await fetch_transfers(OURS, min_block_ms=5, http=http)
    params = seen[0].url.params
    assert (params["contract_address"], params["only_confirmed"], params["only_to"]) == (
        USDT_CONTRACT,
        "true",
        "true",
    )


# --- the poll ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_reads_journals_credits_and_advances_the_cursor(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "120")
    await db_session.commit()
    block = int(now().timestamp() * 1000)
    rows = [
        row(units(r.amount_usdt), block_timestamp=block),
        row("5000000", block_timestamp=block),
        row(units(r.amount_usdt), token_info={"address": tron(7), "decimals": 6}),
    ]
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(_paged(rows)) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
        again = await poll.poll_once(sessions, now_=now(), http=http)

    assert (result.seen, result.matched, result.unmatched) == (2, 1, 1)
    assert again.seen == 0
    async with sessions() as db:
        s = await load_settings(db)
        assert s.cursor_block_ms == block
        assert await deposit_balance(db, merchant_id=m) == r.amount_usdt


@pytest.mark.asyncio
async def test_a_spam_flood_cannot_stall_the_cursor(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """Security review #2: 6 000 zero-value transfers inside the overlap window."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "120")
    await db_session.commit()
    t0 = int((now() - timedelta(minutes=5)).timestamp() * 1000)
    spam = [row("1", block_timestamp=t0 + i) for i in range(6000)]
    real = row(units(r.amount_usdt), block_timestamp=int(now().timestamp() * 1000))
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(_paged([*spam, real])) as http:
        flooded = [await poll.poll_once(sessions, now_=now(), http=http) for _ in range(3)]

    assert flooded[0].truncated is True
    assert sum(p.matched for p in flooded) == 1
    async with sessions() as db:
        assert await deposit_balance(db, merchant_id=m) == r.amount_usdt
        # Dust never reaches the journal: a flood does not grow the table.
        assert len((await db.execute(select(UsdtIncoming.id))).all()) == 1


@pytest.mark.asyncio
async def test_a_failing_transfer_holds_the_cursor_and_alerts(
    db_engine: AsyncEngine, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await open_usdt(db_session, [])
    await db_session.commit()
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        start = (await load_settings(db)).cursor_block_ms
    rows = [row("7000000"), row("8000000")]
    real_ingest = intake.ingest

    async def flaky(db: AsyncSession, t: Any, *, received_at: Any) -> Any:
        if t.amount == Decimal("8"):
            raise RuntimeError("db hiccup")
        return await real_ingest(db, t, received_at=received_at)

    monkeypatch.setattr(poll, "ingest", flaky)
    async with _client(_paged(rows)) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
    assert result.failed is True
    assert [k for k, _ in result.alerts] == ["usdt_unmatched", "usdt_ingest_failed"]
    async with sessions() as db:
        assert (await load_settings(db)).cursor_block_ms == max(
            start or 0, rows[0]["block_timestamp"]
        )

    monkeypatch.setattr(poll, "ingest", real_ingest)
    async with _client(_paged(rows)) as http:
        healed = await poll.poll_once(sessions, now_=now(), http=http)
    assert (healed.failed, healed.unmatched) == (False, 1)


@pytest.mark.asyncio
async def test_a_future_timestamp_cannot_push_the_cursor_ahead(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    await open_usdt(db_session, [])
    await db_session.commit()
    future = int((now() + timedelta(days=30)).timestamp() * 1000)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    at = now()
    async with _client(_paged([row("9000000", block_timestamp=future)])) as http:
        await poll.poll_once(sessions, now_=at, http=http)
    async with sessions() as db:
        assert (await load_settings(db)).cursor_block_ms == int(at.timestamp() * 1000)


@pytest.mark.asyncio
async def test_off_still_polls_while_an_amount_is_held(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """Switching the method off must not strand a reseller who already sent."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "50")
    (await load_settings(db_session)).mode = "off"
    await db_session.commit()
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(_paged([row(units(r.amount_usdt))])) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
    assert result.matched == 1


@pytest.mark.asyncio
async def test_off_with_nothing_held_does_not_poll(db_engine: AsyncEngine) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("polled while off")

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(handler) as http:
        assert (await poll.poll_once(sessions, now_=now(), http=http)).seen == 0
