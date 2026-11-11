"""The USDT switches: who may top up (``usdt_settings``), and on which chains (``usdt_networks``)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.usdt.models import UsdtNetwork, UsdtSettings
from yupay.modules.usdt.networks import CODES


async def load_settings(db: AsyncSession) -> UsdtSettings:
    """The singleton row; created ``off`` if a fresh database lacks it."""
    row = await db.get(UsdtSettings, 1)
    if row is None:
        row = UsdtSettings(id=1, mode="off", allowlist_merchant_ids=[])
        db.add(row)
        await db.flush()
    return row


async def load_networks(db: AsyncSession) -> list[UsdtNetwork]:
    """One row per known chain, in ``networks.CODES`` order; missing ones created off."""
    rows = {r.network: r for r in (await db.execute(select(UsdtNetwork))).scalars()}
    for code in CODES:
        if code not in rows:
            rows[code] = UsdtNetwork(network=code, enabled=False)
            db.add(rows[code])
    await db.flush()
    return [rows[c] for c in CODES]


def admits(s: UsdtSettings, merchant_id: str) -> bool:
    """Whether this merchant may open a USDT top-up at all (any chain)."""
    if s.mode == "all":
        return True
    return s.mode == "allowlist" and merchant_id in (s.allowlist_merchant_ids or [])


def is_open(n: UsdtNetwork) -> bool:
    """Whether resellers can pick this chain: on, given an address, and being read.

    The cursor must exist: after an address change it is cleared, and a
    reservation taken before the poller fixed where to start reading could be
    paid in a block the poller then starts after (security review 2026-11-11).
    """
    return n.enabled and bool(n.address) and n.cursor is not None


__all__ = ["admits", "is_open", "load_networks", "load_settings"]
