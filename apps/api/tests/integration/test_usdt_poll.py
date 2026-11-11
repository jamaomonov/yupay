"""USDT top-up: the TronGrid client and the poll's cursor rules (ADR-0104).

The cursor is what decides whether a transfer is ever read, so each rule the
2026-11-11 reviews found broken has a test here: the spam flood that stalled
it, the failure that silently stopped it, the future timestamp that skipped
ahead, and polling while the method is switched off.
"""

from __future__ import annotations

import json
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
from yupay.modules.usdt import evm, intake, poll
from yupay.modules.usdt.models import UsdtIncoming, UsdtNetwork
from yupay.modules.usdt.networks import BEP20, ERC20
from yupay.modules.usdt.settings import load_settings
from yupay.modules.usdt.tron import (
    USDT_CONTRACT,
    TronUnavailableError,
    fetch_transfers,
    parse_transfer,
)

from tests.integration.p2p_fixtures import _merchant
from tests.integration.usdt_fixtures import (
    EVM_OURS,
    EVM_PAYER,
    OURS,
    open_usdt,
    reserve,
    row,
    tron,
    units,
)

Handler = Callable[[httpx.Request], httpx.Response]


async def _cursor(db: AsyncSession, network: str = "trc20") -> int | None:
    row = await db.get(UsdtNetwork, network)
    assert row is not None
    await db.refresh(row)
    return row.cursor


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
        assert await _cursor(db) == block
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

    assert flooded[0].truncated == ["trc20"]
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
        start = await _cursor(db)
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
        assert await _cursor(db) == max(start or 0, rows[0]["block_timestamp"])

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
        assert await _cursor(db) == int(at.timestamp() * 1000)


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


# --- EVM chains (BEP-20 / ERC-20) ---------------------------------------------------


def _log(
    value: int,
    *,
    block: int,
    index: int = 0,
    contract: str = BEP20.contract,
    to: str = EVM_OURS,
    removed: bool = False,
    tx: str | None = None,
) -> dict[str, Any]:
    return {
        "address": contract.lower(),
        "topics": [
            evm.TRANSFER_TOPIC,
            "0x" + "0" * 24 + EVM_PAYER[2:].lower(),
            "0x" + "0" * 24 + to[2:].lower(),
        ],
        "data": hex(value),
        "blockNumber": hex(block),
        "logIndex": hex(index),
        "transactionHash": tx or "0x" + f"{block:064x}",
        "removed": removed,
    }


def _rpc(head: int, logs: list[dict[str, Any]], seen: list[dict[str, Any]]) -> Handler:
    """A JSON-RPC node: ``eth_blockNumber``, ``eth_getLogs`` over a range, block times."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        method, params = body["method"], body["params"]
        if method == "eth_blockNumber":
            result: Any = hex(head)
        elif method == "eth_getLogs":
            lo, hi = int(params[0]["fromBlock"], 16), int(params[0]["toBlock"], 16)
            result = [log for log in logs if lo <= int(log["blockNumber"], 16) <= hi]
        else:
            result = {"timestamp": hex(int(now().timestamp()))}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    return handler


def _wei(amount: str) -> int:
    return int(Decimal(amount).scaleb(BEP20.decimals))


@pytest.mark.asyncio
async def test_bep20_credits_only_confirmed_real_usdt_to_us(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m], networks=("bep20",), evm_cursor=1000)
    r = await reserve(db_session, m, "150", "bep20")
    await db_session.commit()
    head = 1000 + BEP20.confirmations + 10  # confirmed up to block 1010
    logs = [
        _log(_wei("150"), block=1005, index=3),
        _log(_wei("150"), block=1006, contract="0x" + "1" * 40),  # a fake "USDT"
        _log(_wei("150"), block=1007, removed=True),  # reorged away
        _log(_wei("150"), block=1008, to=EVM_PAYER),  # not to us
        _log(_wei("150"), block=1011),  # not confirmed yet
    ]
    seen: list[dict[str, Any]] = []
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(_rpc(head, logs, seen)) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
    assert (result.matched, result.unmatched) == (1, 0)
    query = next(b for b in seen if b["method"] == "eth_getLogs")["params"][0]
    assert query["address"] == BEP20.contract
    assert int(query["toBlock"], 16) == 1010
    async with sessions() as db:
        assert await deposit_balance(db, merchant_id=m) == r.amount_usdt
        assert await _cursor(db, "bep20") == 1010
        journal = (await db.execute(select(UsdtIncoming))).scalars().all()
        assert [(j.network, j.event_key) for j in journal] == [("bep20", "3")]


@pytest.mark.asyncio
async def test_a_new_evm_address_starts_at_the_head_and_reads_no_history(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    await open_usdt(db_session, [], mode="all", networks=("erc20",))
    row = await db_session.get(UsdtNetwork, "erc20")
    assert row is not None
    row.cursor = None
    await db_session.commit()
    seen: list[dict[str, Any]] = []
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(_rpc(5000, [_log(_wei("9"), block=4000)], seen)) as http:
        await poll.poll_once(sessions, now_=now(), http=http)
    assert [b["method"] for b in seen] == ["eth_blockNumber"]
    async with sessions() as db:
        assert await _cursor(db, "erc20") == 5000 - ERC20.confirmations


@pytest.mark.asyncio
async def test_one_chain_down_does_not_stop_another(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m], networks=("trc20", "bep20"))
    r = await reserve(db_session, m, "70")
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":  # the BSC node
            return httpx.Response(502)
        return _paged([row(units(r.amount_usdt))])(request)

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with _client(handler) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
    assert (result.matched, result.unavailable) == (1, ["bep20"])
