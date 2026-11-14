"""Shared helpers for the USDT (TRC20) top-up integration tests (ADR-0104)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.usdt import reservations
from yupay.modules.usdt.chain import Transfer
from yupay.modules.usdt.models import UsdtReservation
from yupay.modules.usdt.settings import load_networks, load_settings
from yupay.modules.usdt.tron import USDT_CONTRACT

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def tron(seed: int) -> str:
    """A valid mainnet TRON address made from ``seed`` (base58check, prefix 0x41)."""
    payload = b"\x41" + hashlib.sha256(str(seed).encode()).digest()[:20]
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    num = int.from_bytes(raw, "big")
    out = ""
    while num:
        num, rem = divmod(num, 58)
        out = _B58[rem] + out
    return out


OURS = tron(1)
PAYER = tron(2)


#: A checksummed EVM address for BEP-20 / ERC-20 tests (EIP-55 spec vector).
EVM_OURS = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
EVM_PAYER = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"


async def open_usdt(
    db: AsyncSession,
    merchant_ids: list[str],
    *,
    mode: str = "allowlist",
    networks: tuple[str, ...] = ("trc20",),
    evm_cursor: int = 1000,
) -> None:
    """Admit ``merchant_ids`` and open ``networks``: TRON at ``OURS`` with a cursor an
    hour back, EVM chains at ``EVM_OURS`` with ``evm_cursor`` as the last block read."""
    s = await load_settings(db)
    s.mode, s.allowlist_merchant_ids = mode, merchant_ids
    for n in await load_networks(db):
        n.enabled = n.network in networks
        if n.network == "trc20":
            n.address = OURS
            n.cursor = int((now() - timedelta(hours=1)).timestamp() * 1000)
        else:
            n.address = EVM_OURS
            n.cursor = evm_cursor
        n.cursor_exact = False
    await db.flush()


async def reserve(
    db: AsyncSession, merchant_id: str, amount: str, network: str = "trc20"
) -> UsdtReservation:
    """A reservation for exactly ``amount`` on ``network``, made two minutes ago.

    Backdated so a transfer "now" reads as an honest payer's, past intake's
    60-second front-running guard; the guard has its own test.
    """
    r = await reservations.reserve(
        db, merchant_id=merchant_id, network=network, amount=Decimal(amount), idempotency_key=None
    )
    r.created_at = r.created_at - timedelta(minutes=2)
    r.expires_at = r.expires_at - timedelta(minutes=2)
    await db.flush()
    return r


def transfer(
    amount: Decimal | str,
    *,
    at_offset: timedelta = timedelta(0),
    tx: str | None = None,
    sender: str = PAYER,
    network: str = "trc20",
    event_key: str | None = None,
) -> Transfer:
    """A confirmed transfer of ``amount`` to our address at now + ``at_offset``."""
    at = now() + at_offset
    return Transfer(
        network=network,
        tx_id=tx or hashlib.sha256(new_id().encode()).hexdigest(),
        event_key=event_key or f"{sender}:{amount}",
        from_address=sender,
        to_address=OURS if network == "trc20" else EVM_OURS,
        amount=Decimal(amount),
        block_at=at,
        position=int(at.timestamp() * 1000),
    )


def row(amount_units: str, **over: Any) -> dict[str, Any]:
    """One TronGrid ``data`` element for a USDT transfer to ``OURS``."""
    item: dict[str, Any] = {
        "transaction_id": hashlib.sha256(new_id().encode()).hexdigest(),
        "token_info": {"address": USDT_CONTRACT, "decimals": 6, "symbol": "USDT"},
        "block_timestamp": int(now().timestamp() * 1000),
        "from": PAYER,
        "to": OURS,
        "type": "Transfer",
        "value": amount_units,
    }
    item.update(over)
    return item


def units(amount: Decimal) -> str:
    """``amount`` USDT as TronGrid's integer ``value`` (6 decimals)."""
    return str(int(amount.scaleb(6)))


__all__ = [
    "EVM_OURS",
    "EVM_PAYER",
    "OURS",
    "PAYER",
    "open_usdt",
    "reserve",
    "row",
    "transfer",
    "tron",
    "units",
]
