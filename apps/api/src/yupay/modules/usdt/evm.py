"""Read confirmed USDT transfers to one address on an EVM chain (BEP-20, ERC-20).

Plain JSON-RPC, no indexer: ``eth_getLogs`` for the ``Transfer`` event of the
chain's USDT contract with our address as the indexed recipient, over blocks
already buried ``confirmations`` deep. Each log is checked again — the
emitting contract, the event topic, the recipient — so a token that calls
itself "USDT" from another contract never becomes a :class:`Transfer`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import httpx

from yupay.modules.usdt.address import evm_checksum
from yupay.modules.usdt.chain import DUST, Batch, ChainUnavailableError, Transfer
from yupay.modules.usdt.networks import Network

#: keccak256("Transfer(address,address,uint256)").
TRANSFER_TOPIC: Final = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_TIMEOUT_SECONDS: Final = 10.0


class EvmUnavailableError(ChainUnavailableError):
    """The RPC node did not answer usably; the caller retries on the next tick."""


def _topic_for(address: str) -> str:
    """An address as a 32-byte indexed topic."""
    return "0x" + "0" * 24 + address[2:].lower()


def _hex_int(value: object) -> int | None:
    if not isinstance(value, str) or not value.startswith("0x"):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


class _Rpc:
    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        self._client, self._url, self._id = client, url, 0

    # ``Any``: a JSON-RPC result; every caller type-checks what it reads.
    async def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        try:
            resp = await self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise EvmUnavailableError(type(exc).__name__) from exc
        if resp.status_code != 200:
            raise EvmUnavailableError(f"status {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise EvmUnavailableError("not json") from exc
        if not isinstance(payload, dict) or "error" in payload or "result" not in payload:
            raise EvmUnavailableError("rpc error")
        return payload["result"]


async def chain_head(net: Network, *, url: str, http: httpx.AsyncClient | None = None) -> int:
    """The newest block buried ``confirmations`` deep — where a fresh cursor starts."""
    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        rpc = _Rpc(client, url)
        if _hex_int(await rpc.call("eth_chainId", [])) != net.chain_id:
            raise EvmUnavailableError("wrong chain")
        head = _hex_int(await rpc.call("eth_blockNumber", []))
    finally:
        if http is None:
            await client.aclose()
    if head is None:
        raise EvmUnavailableError("bad block number")
    return max(0, head - net.confirmations)


# ``Any``: one decoded log object, checked field by field.
def parse_log(log: dict[str, Any], net: Network, address: str) -> tuple[Transfer, int] | None:
    """A transfer (without its block time yet) and its block number, or ``None``.

    Args:
        log: One element of an ``eth_getLogs`` result.
        net: The chain.
        address: Our receiving address (checksummed).

    Returns:
        ``None`` unless the log is our USDT contract's ``Transfer`` to us with
        a positive value and well-formed fields, and was not removed by a reorg.
    """
    topics = log.get("topics")
    ours = (
        log.get("removed") is not True
        and str(log.get("address", "")).lower() == net.contract.lower()
        and isinstance(topics, list)
        and len(topics) == 3
        and str(topics[0]).lower() == TRANSFER_TOPIC
        and str(topics[2]).lower() == _topic_for(address)
    )
    if not ours or not isinstance(topics, list):
        return None
    value, block, index = (
        _hex_int(log.get("data")),
        _hex_int(log.get("blockNumber")),
        _hex_int(log.get("logIndex")),
    )
    tx_id, sender = log.get("transactionHash"), str(topics[1])
    # Dust (under 1 USDT, incl. 1-wei poisoning spam) stops here, before it
    # costs a block lookup or a journal row (security review 2026-11-11).
    if value is None or value < DUST.scaleb(net.decimals) or block is None or index is None:
        return None
    if not isinstance(tx_id, str) or len(tx_id) != 66 or len(sender) != 66:
        return None
    transfer = Transfer(
        network=net.code,
        tx_id=tx_id.lower(),
        event_key=str(index),
        from_address=evm_checksum("0x" + sender[-40:]),
        to_address=address,
        amount=Decimal(value).scaleb(-net.decimals),
        # Nodes include ``blockTimestamp`` in every log (checked on publicnode);
        # a node that omits it costs one ``eth_getBlockByNumber`` per block.
        block_at=datetime.fromtimestamp(_hex_int(log.get("blockTimestamp")) or 0, tz=UTC),
        position=block,
    )
    return transfer, block


async def _block_time(rpc: _Rpc, block: int, cache: dict[int, datetime]) -> datetime:
    if block not in cache:
        found = await rpc.call("eth_getBlockByNumber", [hex(block), False])
        stamp = _hex_int(found.get("timestamp")) if isinstance(found, dict) else None
        if stamp is None:
            raise EvmUnavailableError("bad block")
        cache[block] = datetime.fromtimestamp(stamp, tz=UTC)
    return cache[block]


#: ``eth_getLogs`` calls per read, halvings included: 1000 → 1 block is ten.
_MAX_LOG_CALLS: Final = 30


async def _logs(rpc: _Rpc, net: Network, address: str, start: int, end: int) -> list[Any]:
    logs = await rpc.call(
        "eth_getLogs",
        [
            {
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "address": net.contract,
                "topics": [TRANSFER_TOPIC, None, _topic_for(address)],
            }
        ],
    )
    if not isinstance(logs, list):
        raise EvmUnavailableError("bad logs")
    return logs


async def _collect(
    rpc: _Rpc,
    net: Network,
    address: str,
    logs: list[Any],
    start: int,
    end: int,
    times: dict[int, datetime],
) -> list[Transfer]:
    out: list[Transfer] = []
    for item in logs:
        parsed = parse_log(item, net, address) if isinstance(item, dict) else None
        if parsed is None:
            continue
        t, block = parsed
        # A node must not hand back a log outside the range asked — that is
        # how an unconfirmed block could slip in.
        if not start <= block <= end:
            raise EvmUnavailableError("log outside the requested range")
        if t.block_at.timestamp() == 0:
            t = replace(t, block_at=await _block_time(rpc, block, times))
        out.append(t)
    return out


async def fetch_transfers(
    net: Network,
    address: str,
    *,
    after_block: int,
    url: str,
    http: httpx.AsyncClient | None = None,
) -> Batch:
    """Confirmed USDT transfers to ``address`` in blocks after ``after_block``.

    The range starts at ``net.max_blocks`` and is **halved** whenever the node
    refuses it (too many results, a timeout) down to one block, so a flood of
    spam logs slows the read instead of stopping it. Ranges already read are
    kept: the batch reports how far it got (``last_position``) and is
    ``truncated`` when the confirmed head is further.

    Raises:
        EvmUnavailableError: When the node is unusable before anything was
            read — head, chain id, or a single block it will not return.
    """
    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    rpc = _Rpc(client, url)
    out: list[Transfer] = []
    times: dict[int, datetime] = {}
    try:
        if _hex_int(await rpc.call("eth_chainId", [])) != net.chain_id:
            raise EvmUnavailableError("wrong chain")
        head = _hex_int(await rpc.call("eth_blockNumber", []))
        if head is None:
            raise EvmUnavailableError("bad block number")
        safe = head - net.confirmations
        start, last, span = after_block + 1, after_block, net.max_blocks
        for _ in range(_MAX_LOG_CALLS):
            if start > safe:
                break
            end = min(safe, start + span - 1)
            try:
                logs = await _logs(rpc, net, address, start, end)
                found = await _collect(rpc, net, address, logs, start, end, times)
            except EvmUnavailableError:
                if span > 1:
                    span = max(1, span // 2)
                    continue
                if last > after_block:
                    break  # keep what was read; the next tick resumes here
                raise
            out.extend(found)
            last, start = end, end + 1
            span = min(net.max_blocks, span * 2)
    finally:
        if http is None:
            await client.aclose()
    out.sort(key=lambda t: (t.position, int(t.event_key)))
    return Batch(transfers=out, last_position=last, truncated=last < safe)


__all__ = ["TRANSFER_TOPIC", "EvmUnavailableError", "chain_head", "fetch_transfers", "parse_log"]
