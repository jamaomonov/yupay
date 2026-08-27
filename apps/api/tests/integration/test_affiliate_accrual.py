"""Affiliate commission: ledger accounts, accrual, maturation, voiding.

The sweep is idempotent by construction — ``UNIQUE(order_id)`` on
``affiliate_commissions`` — so these tests lean on running it twice rather than
on mocking a scheduler.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# Reach into ``service`` rather than the ``api`` facade: the facade imports the
# wallet router, which pulls in the whole v1 route stack and circles back here.
# The affiliate module's own ledger.py does the same, for the same reason plus
# one more: the scheduler imports it, and a scheduler process has no business
# loading FastAPI routes.
from yupay.modules.wallet import service as wallet_service

pytestmark = pytest.mark.asyncio

AFFILIATE_KINDS = [
    "partner_pending",
    "partner_balance",
    "partner_payout_hold",
    "house_affiliate_expense",
    "house_affiliate_paid",
]


@pytest.mark.parametrize("kind", AFFILIATE_KINDS)
async def test_affiliate_account_kinds_are_postable(db_session: AsyncSession, kind: str) -> None:
    """Every affiliate account kind can be created through the wallet facade."""
    owner_type = "house" if kind.startswith("house_") else "partner"
    account = await wallet_service.ensure_account(
        db_session,
        owner_type=owner_type,
        owner_id="house" if owner_type == "house" else "00000000-0000-0000-0000-000000000001",
        kind=kind,
        currency="UZS",
    )
    assert account.kind == kind
    assert await wallet_service.balance(db_session, account.id) == Decimal("0")
