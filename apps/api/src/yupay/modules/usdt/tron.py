"""Read confirmed USDT (TRC20) transfers to one address from TronGrid (ADR-0104).

Only what TronGrid itself returns for ``only_to`` + ``only_confirmed`` + the USDT
contract is requested, and every row is checked again here: the contract, the
recipient, the type and the decimals. A token that calls itself "USDT" from
another contract never becomes a :class:`Transfer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import httpx

from yupay.core.config import Settings, get_settings
from yupay.core.logging import get_logger

log = get_logger("yupay.usdt.tron")

#: Tether's USDT on TRON mainnet. Nothing else is money here.
USDT_CONTRACT: Final = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
_DECIMALS: Final = 6
_PAGE: Final = 200
_MAX_PAGES: Final = 10
_TIMEOUT_SECONDS: Final = 10.0


class TronUnavailableError(Exception):
    """TronGrid did not answer usably; the caller retries on the next tick."""


@dataclass(frozen=True)
class Transfer:
    """One confirmed USDT transfer to our address."""

    tx_id: str
    from_address: str
    to_address: str
    amount: Decimal
    block_at: datetime
    block_ms: int


def _fields(item: dict[str, Any]) -> tuple[str, str, str, int] | None:
    """``(tx_id, from, value, block_timestamp)`` when each has TronGrid's type."""
    tx_id, sender, value, block_ms = (
        item.get("transaction_id"),
        item.get("from"),
        item.get("value"),
        item.get("block_timestamp"),
    )
    if not isinstance(tx_id, str) or not 0 < len(tx_id) <= 64:
        return None
    if not isinstance(sender, str) or not isinstance(value, str) or not value.isdigit():
        return None
    if not isinstance(block_ms, int) or isinstance(block_ms, bool):
        return None
    return tx_id, sender, value, block_ms


def parse_transfer(item: dict[str, Any], address: str) -> Transfer | None:
    """A :class:`Transfer` from one TronGrid row, or ``None`` if it is not ours to count.

    Args:
        item: One element of TronGrid's ``data`` array.
        address: Our receiving address.

    Returns:
        The transfer when the contract, recipient, type and decimals all hold
        and the value is a non-negative integer string; otherwise ``None``.
    """
    token = item.get("token_info")
    ours = (
        isinstance(token, dict)
        and token.get("address") == USDT_CONTRACT
        and str(token.get("decimals")) == str(_DECIMALS)
        and item.get("type") == "Transfer"
        and item.get("to") == address
    )
    fields = _fields(item) if ours else None
    if fields is None:
        return None
    tx_id, sender, value, block_ms = fields
    return Transfer(
        tx_id=tx_id,
        from_address=sender[:34],
        to_address=address,
        amount=Decimal(value).scaleb(-_DECIMALS),
        block_at=datetime.fromtimestamp(block_ms / 1000, tz=UTC),
        block_ms=block_ms,
    )


async def fetch_transfers(
    address: str,
    *,
    min_block_ms: int,
    http: httpx.AsyncClient | None = None,
    settings: Settings | None = None,
) -> list[Transfer]:
    """Every confirmed USDT transfer to ``address`` at or after ``min_block_ms``, oldest first.

    Follows TronGrid's ``fingerprint`` paging up to ``_MAX_PAGES`` pages; a
    longer backlog is read on the next tick from the advanced cursor.

    Raises:
        TronUnavailableError: On a transport error, a non-200, or a body that
            is not TronGrid's shape. Nothing partial is returned.
    """
    s = settings or get_settings()
    headers = {"Accept": "application/json"}
    if s.trongrid_api_key:
        headers["TRON-PRO-API-KEY"] = s.trongrid_api_key
    url = f"{s.trongrid_base_url.rstrip('/')}/v1/accounts/{address}/transactions/trc20"
    params: dict[str, str | int] = {
        "only_to": "true",
        "only_confirmed": "true",
        "contract_address": USDT_CONTRACT,
        "min_timestamp": min_block_ms,
        "order_by": "block_timestamp,asc",
        "limit": _PAGE,
    }
    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    out: list[Transfer] = []
    try:
        for _ in range(_MAX_PAGES):
            try:
                resp = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise TronUnavailableError(type(exc).__name__) from exc
            if resp.status_code != 200:
                raise TronUnavailableError(f"status {resp.status_code}")
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list) or body.get("success") is False:
                raise TronUnavailableError("unexpected body")
            out.extend(
                t
                for item in data
                if isinstance(item, dict) and (t := parse_transfer(item, address))
            )
            fingerprint = (body.get("meta") or {}).get("fingerprint")
            if len(data) < _PAGE or not isinstance(fingerprint, str) or not fingerprint:
                break
            params["fingerprint"] = fingerprint
    finally:
        if http is None:
            await client.aclose()
    return out


__all__ = ["USDT_CONTRACT", "Transfer", "TronUnavailableError", "fetch_transfers", "parse_transfer"]
