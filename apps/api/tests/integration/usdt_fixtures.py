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
from yupay.modules.usdt.models import UsdtReservation
from yupay.modules.usdt.settings import load_settings
from yupay.modules.usdt.tron import USDT_CONTRACT, Transfer

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


async def open_usdt(db: AsyncSession, merchant_ids: list[str], *, mode: str = "allowlist") -> None:
    """Admit ``merchant_ids`` with ``OURS`` as the address and a cursor an hour back."""
    s = await load_settings(db)
    s.mode, s.allowlist_merchant_ids, s.address = mode, merchant_ids, OURS
    s.cursor_block_ms = int((now() - timedelta(hours=1)).timestamp() * 1000)
    s.cursor_exact = False
    await db.flush()


async def reserve(db: AsyncSession, merchant_id: str, amount: str) -> UsdtReservation:
    """A reservation for ``amount`` (its stored amount carries random cents)."""
    return await reservations.reserve(
        db, merchant_id=merchant_id, amount=Decimal(amount), idempotency_key=None
    )


def transfer(
    amount: Decimal | str,
    *,
    at_offset: timedelta = timedelta(0),
    tx: str | None = None,
    sender: str = PAYER,
) -> Transfer:
    """A confirmed transfer of ``amount`` to ``OURS`` at now + ``at_offset``."""
    at = now() + at_offset
    return Transfer(
        tx_id=tx or hashlib.sha256(new_id().encode()).hexdigest(),
        from_address=sender,
        to_address=OURS,
        amount=Decimal(amount),
        block_at=at,
        block_ms=int(at.timestamp() * 1000),
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


__all__ = ["OURS", "PAYER", "open_usdt", "reserve", "row", "transfer", "tron", "units"]
