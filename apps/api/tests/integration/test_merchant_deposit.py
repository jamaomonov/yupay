"""Merchant USD deposit on the double-entry ledger (Merchant B2B M1, Task 3).

The money-path set from the task brief, plus the guard rails the ≥95%
coverage gate on money modules asks for. Directions are pinned against the
posting table in ``modules/merchants/README.md``: a support credit is
``D merchant_deposit / C house_payments_received``.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.merchants import deposit as merchants_deposit
from yupay.modules.merchants import service as merchants_service
from yupay.modules.wallet.models import WalletAccount, WalletTransaction

pytestmark = pytest.mark.asyncio


async def _account(
    db: AsyncSession, *, owner_type: str, owner_id: str, kind: str
) -> WalletAccount | None:
    stmt = select(WalletAccount).where(
        WalletAccount.owner_type == owner_type,
        WalletAccount.owner_id == owner_id,
        WalletAccount.kind == kind,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------- the brief's money-path set ----------


async def test_credit_shows_up_in_balance(db_session: AsyncSession) -> None:
    merchant = await merchants_service.create_merchant(db_session, title="Reseller One")
    txn = await merchants_deposit.credit_deposit(
        db_session,
        merchant_id=merchant.id,
        amount=Decimal("100.00"),
        actor="admin:test",
        idempotency_key="merchant-credit-1",
        note="first top-up",
    )
    balance = await merchants_deposit.deposit_balance(db_session, merchant_id=merchant.id)
    assert balance == Decimal("100.00")

    # Pin the posting directions: D merchant_deposit / C house_payments_received.
    deposit_acc = await _account(
        db_session, owner_type="merchant", owner_id=merchant.id, kind="merchant_deposit"
    )
    house_acc = await _account(
        db_session, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    assert deposit_acc is not None
    assert deposit_acc.currency == "USD"
    assert house_acc is not None
    directions = {p.account_id: p.direction for p in txn.postings}
    assert directions == {deposit_acc.id: "D", house_acc.id: "C"}
    assert txn.kind == "merchant_deposit_credit"
    assert txn.actor == "admin:test"
    assert txn.extra_metadata == {"note": "first top-up"}


async def test_credit_is_idempotent_by_key(db_session: AsyncSession) -> None:
    merchant = await merchants_service.create_merchant(db_session, title="Reseller Two")
    first = await merchants_deposit.credit_deposit(
        db_session,
        merchant_id=merchant.id,
        amount=Decimal("50.00"),
        actor="admin:test",
        idempotency_key="merchant-credit-replay",
        note=None,
    )
    second = await merchants_deposit.credit_deposit(
        db_session,
        merchant_id=merchant.id,
        amount=Decimal("50.00"),
        actor="admin:test",
        idempotency_key="merchant-credit-replay",
        note=None,
    )
    assert second.id == first.id

    balance = await merchants_deposit.deposit_balance(db_session, merchant_id=merchant.id)
    assert balance == Decimal("50.00")

    txn_count = len(
        (
            await db_session.execute(
                select(WalletTransaction).where(WalletTransaction.kind == "merchant_deposit_credit")
            )
        )
        .scalars()
        .all()
    )
    assert txn_count == 1


async def test_two_concurrent_credits_both_land(db_engine: AsyncEngine) -> None:
    """Two credits with *different* keys race; both must land, sum must hold.

    Each coroutine gets its own session (its own connection + transaction), so
    the ``ensure_account`` unique-index race and the ledger inserts are
    exercised under genuine concurrency, not sequential awaits.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        merchant = await merchants_service.create_merchant(setup, title="Concurrent LLC")
        merchant_id = merchant.id
        await setup.commit()

    async def _credit(key: str, amount: str) -> None:
        async with factory() as session:
            await merchants_deposit.credit_deposit(
                session,
                merchant_id=merchant_id,
                amount=Decimal(amount),
                actor="admin:test",
                idempotency_key=key,
                note=None,
            )
            await session.commit()

    await asyncio.gather(
        _credit("merchant-concurrent-a", "40.00"),
        _credit("merchant-concurrent-b", "60.00"),
    )

    async with factory() as check:
        balance = await merchants_deposit.deposit_balance(check, merchant_id=merchant_id)
        assert balance == Decimal("100.00")


async def test_frozen_merchant_can_still_be_credited(db_session: AsyncSession) -> None:
    """Freezing blocks ORDERS (M2), never money in — support can always credit."""
    merchant = await merchants_service.create_merchant(db_session, title="Frozen Ltd")
    frozen = await merchants_service.set_status(
        db_session, merchant_id=merchant.id, status="frozen"
    )
    assert frozen.status == "frozen"

    await merchants_deposit.credit_deposit(
        db_session,
        merchant_id=merchant.id,
        amount=Decimal("25.00"),
        actor="admin:test",
        idempotency_key="merchant-credit-frozen",
        note=None,
    )
    balance = await merchants_deposit.deposit_balance(db_session, merchant_id=merchant.id)
    assert balance == Decimal("25.00")


async def test_balance_of_unknown_merchant_is_zero(db_session: AsyncSession) -> None:
    balance = await merchants_deposit.deposit_balance(
        db_session, merchant_id="00000000-0000-0000-0000-000000000000"
    )
    assert balance == Decimal("0")


# ---------- guard rails ----------


async def test_credit_rejects_non_positive_amount(db_session: AsyncSession) -> None:
    merchant = await merchants_service.create_merchant(db_session, title="Zero Inc")
    for bad in (Decimal("0"), Decimal("-10.00")):
        with pytest.raises(ValidationError):
            await merchants_deposit.credit_deposit(
                db_session,
                merchant_id=merchant.id,
                amount=bad,
                actor="admin:test",
                idempotency_key=f"merchant-credit-bad-{bad}",
                note=None,
            )


async def test_credit_unknown_merchant_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await merchants_deposit.credit_deposit(
            db_session,
            merchant_id="00000000-0000-0000-0000-000000000000",
            amount=Decimal("10.00"),
            actor="admin:test",
            idempotency_key="merchant-credit-ghost",
            note=None,
        )


async def test_create_merchant_rejects_blank_title(db_session: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await merchants_service.create_merchant(db_session, title="   ")


async def test_set_status_rejects_unknown_status(db_session: AsyncSession) -> None:
    merchant = await merchants_service.create_merchant(db_session, title="Status Co")
    with pytest.raises(ValidationError):
        await merchants_service.set_status(db_session, merchant_id=merchant.id, status="suspended")


async def test_set_status_of_unknown_merchant_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await merchants_service.set_status(
            db_session,
            merchant_id="00000000-0000-0000-0000-000000000000",
            status="frozen",
        )


def test_module_facade_reexports_the_service() -> None:
    """Other modules import ``merchants.api`` — pin that it exposes the service."""
    from yupay.modules.merchants import api as merchants_api

    assert merchants_api.credit_deposit is merchants_deposit.credit_deposit
    assert merchants_api.deposit_balance is merchants_deposit.deposit_balance
    assert merchants_api.create_merchant is merchants_service.create_merchant
    assert merchants_api.set_status is merchants_service.set_status
    assert merchants_api.DEPOSIT_CURRENCY == "USD"
