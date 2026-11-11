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
from yupay.modules.usdt.chain import Batch, ChainUnavailableError, Transfer
from yupay.modules.usdt.networks import Network

#: keccak256("Transfer(address,address,uint256)").
TRANSFER_TOPIC: Final = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_CHUNKS_PER_READ: Final = 5
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
        head = _hex_int(await _Rpc(client, url).call("eth_blockNumber", []))
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
    if value is None or value <= 0 or block is None or index is None:
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
        block_at=datetime.fromtimestamp(0, tz=UTC),
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


async def fetch_transfers(
    net: Network,
    address: str,
    *,
    after_block: int,
    url: str,
    http: httpx.AsyncClient | None = None,
) -> Batch:
    """Confirmed USDT transfers to ``address`` in blocks after ``after_block``.

    Reads at most ``_CHUNKS_PER_READ`` ranges of ``net.max_blocks``; when the
    confirmed head is further away the batch is ``truncated`` and the next
    poll continues from ``last_position``.

    Raises:
        EvmUnavailableError: On any transport, HTTP or JSON-RPC failure.
            Nothing partial is returned.
    """
    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    rpc = _Rpc(client, url)
    out: list[Transfer] = []
    times: dict[int, datetime] = {}
    try:
        head = _hex_int(await rpc.call("eth_blockNumber", []))
        if head is None:
            raise EvmUnavailableError("bad block number")
        safe = head - net.confirmations
        start, last = after_block + 1, after_block
        for _ in range(_CHUNKS_PER_READ):
            if start > safe:
                break
            end = min(safe, start + net.max_blocks - 1)
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
            for item in logs:
                parsed = parse_log(item, net, address) if isinstance(item, dict) else None
                if parsed is not None:
                    t, block = parsed
                    out.append(replace(t, block_at=await _block_time(rpc, block, times)))
            last, start = end, end + 1
    finally:
        if http is None:
            await client.aclose()
    out.sort(key=lambda t: (t.position, int(t.event_key)))
    return Batch(transfers=out, last_position=last, truncated=last < safe)


__all__ = ["TRANSFER_TOPIC", "EvmUnavailableError", "chain_head", "fetch_transfers", "parse_log"]
