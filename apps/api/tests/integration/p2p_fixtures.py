"""Shared helpers for the P2P integration tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import AppError
from yupay.core.ids import new_id
from yupay.modules.merchants import service as merchants_service
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.cards import seal_pan
from yupay.modules.p2p.models import P2PCard
from yupay.modules.p2p.settings import load_settings

RATE = Decimal("12300")


@pytest.fixture(autouse=True)
def _fixed_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _rate(db: AsyncSession, *, quote: str, override_cache: object = None) -> Decimal:
        return RATE

    monkeypatch.setattr(svc, "guarded_usd_rate", _rate)


def _code(exc: AppError) -> object:
    """``AppError`` keeps ``code=`` in ``extra`` (core.errors), not as an attribute."""
    return exc.extra.get("code")


async def _card(db: AsyncSession, **over: object) -> P2PCard:
    ct, nonce = seal_pan("9860350146023311")
    fields: dict[str, object] = {
        "id": new_id(),
        "label": "Humo main",
        "pan_ciphertext": ct,
        "pan_nonce": nonce,
        "pan_last4": "3311",
        "holder_name": "OMONOV J",
        "network": "humo",
        **over,
    }
    card = P2PCard(**fields)
    db.add(card)
    await db.flush()
    return card


async def _merchant(db: AsyncSession) -> str:
    """A merchant with its deposit account, the way test_merchant_deposit.py makes one."""
    merchant = await merchants_service.create_merchant(db, title=f"Reseller {new_id()[-6:]}")
    return merchant.id


async def _open(db: AsyncSession, merchant_ids: list[str]) -> None:
    s = await load_settings(db)
    s.mode = "allowlist"
    s.allowlist_merchant_ids = merchant_ids
    await db.flush()
