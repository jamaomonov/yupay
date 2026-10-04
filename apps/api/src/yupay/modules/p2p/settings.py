"""The P2P switch row: who may top up, and which Telegram id is the HUMO bot."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.p2p.models import P2PSettings


async def load_settings(db: AsyncSession) -> P2PSettings:
    """The singleton row; created ``off`` if a fresh database lacks it."""
    row = await db.get(P2PSettings, 1)
    if row is None:
        row = P2PSettings(id=1, mode="off", allowlist_merchant_ids=[])
        db.add(row)
        await db.flush()
    return row


def admits(s: P2PSettings, merchant_id: str) -> bool:
    """Whether this merchant may open a P2P top-up right now."""
    if s.mode == "all":
        return True
    return s.mode == "allowlist" and merchant_id in (s.allowlist_merchant_ids or [])


__all__ = ["admits", "load_settings"]
