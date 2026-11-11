"""The USDT switch row: who may top up, and the address they send to."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.usdt.models import UsdtSettings


async def load_settings(db: AsyncSession) -> UsdtSettings:
    """The singleton row; created ``off`` if a fresh database lacks it."""
    row = await db.get(UsdtSettings, 1)
    if row is None:
        row = UsdtSettings(id=1, mode="off", allowlist_merchant_ids=[])
        db.add(row)
        await db.flush()
    return row


def admits(s: UsdtSettings, merchant_id: str) -> bool:
    """Whether this merchant may open a USDT top-up right now.

    No address means nowhere to send, so nobody is admitted whatever the mode.
    """
    if not s.address:
        return False
    if s.mode == "all":
        return True
    return s.mode == "allowlist" and merchant_id in (s.allowlist_merchant_ids or [])


__all__ = ["admits", "load_settings"]
