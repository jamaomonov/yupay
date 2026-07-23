"""Integration tests for the Click Shop API stale-prepare sweep (Task 7).

Click's Shop API contract has ``/prepare`` register a ``PREPARED`` transaction
that Click itself is expected to follow up on with ``/complete`` once the
customer finishes paying on ``my.click.uz`` / Click Up. If ``/complete`` never
arrives (buyer abandonment, dropped callback), the transaction — and the
``payments`` row it backs — would sit ``pending`` forever. These tests
exercise ``yupay_scheduler.jobs.click_timeout.run_click_timeout`` end to end
against a directly-seeded ``Order`` + ``Payment`` + ``ClickTransaction``
(bypassing ``/prepare``/``/complete`` entirely), mirroring
``test_uzum_timeout.py``'s own-session redirection and direct-seeding style.

No real sleeping: ``prepare_time`` (a genuine ``timestamptz``, unlike Uzum's
epoch-ms ``create_time``) is seeded directly at a clearly-old or
clearly-recent value rather than waiting out ``click_timeout.TIMEOUT`` in real
time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Importing yupay.api.v1 first avoids the payments.service <-> wallet.routes
# <-> api.v1 import cycle -- see click_timeout.py's module docstring and
# test_click_service.py, which hits the exact same trap.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.ids import new_id
from yupay.modules.click.models import ClickTransaction
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay_scheduler.jobs import click_timeout

pytestmark = pytest.mark.asyncio

_SERVICE_ID = 108149
_AMOUNT = Decimal("130000.000000")


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """The job never uses the request-scoped ``db_session`` fixture -- in
    production it resolves its own factory via ``get_session_factory()``.
    Point that at the truncated test container so the job's sessions and the
    test's assertion session (``db_session``) see the same database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(click_timeout, "get_session_factory", lambda: factory)


async def _seed_order(db: AsyncSession, *, total_charged: Decimal = Decimal("130000.00")) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=None,
            guest_email="click-timeout@example.test",
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=total_charged,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db.flush()
    return order_id


async def _seed_payment(db: AsyncSession, *, order_id: str, status: str = "pending") -> str:
    payment_id = new_id()
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="click",
            status=status,
            amount=_AMOUNT,
            currency="UZS",
            external_id=f"click:{order_id}",
        )
    )
    await db.flush()
    return payment_id


async def _seed_transaction(
    db: AsyncSession,
    *,
    order_id: str,
    payment_id: str | None,
    status: str,
    prepare_time: datetime,
    click_trans_id: int,
) -> str:
    txn_id = new_id()
    db.add(
        ClickTransaction(
            id=txn_id,
            click_trans_id=click_trans_id,
            service_id=_SERVICE_ID,
            order_id=order_id,
            payment_id=payment_id,
            amount=_AMOUNT,
            status=status,
            prepare_time=prepare_time,
        )
    )
    await db.commit()
    return txn_id


_FRESH = {"populate_existing": True}


async def _reload_txn(db: AsyncSession, txn_id: str) -> ClickTransaction:
    return (
        await db.execute(
            select(ClickTransaction)
            .where(ClickTransaction.id == txn_id)
            .execution_options(**_FRESH)
        )
    ).scalar_one()


async def _reload_payment(db: AsyncSession, payment_id: str) -> Payment:
    return (
        await db.execute(
            select(Payment).where(Payment.id == payment_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def test_stale_prepared_transaction_is_cancelled(db_session: AsyncSession) -> None:
    """A PREPARED transaction whose prepare_time is 31 minutes old is
    cancelled (status -> CANCELLED), and its backing pending payment ->
    cancelled."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id)
    old_prepare_time = datetime.now(UTC) - timedelta(minutes=31)
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="PREPARED",
        prepare_time=old_prepare_time,
        click_trans_id=9001,
    )

    await click_timeout.run_click_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "CANCELLED"
    assert txn.cancel_time is not None
    assert txn.complete_time is None

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "cancelled"


async def test_fresh_prepared_transaction_is_untouched(db_session: AsyncSession) -> None:
    """A PREPARED transaction only 5 minutes old is well within the 30-minute
    timeout and must be left completely alone."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id)
    recent_prepare_time = datetime.now(UTC) - timedelta(minutes=5)
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="PREPARED",
        prepare_time=recent_prepare_time,
        click_trans_id=9002,
    )

    await click_timeout.run_click_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "PREPARED"

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "pending"


async def test_confirmed_transaction_is_never_touched(db_session: AsyncSession) -> None:
    """A CONFIRMED transaction is never touched by the timeout sweep, no
    matter how old prepare_time is -- only PREPARED is in scope. This is the
    money-safety invariant: a settled payment must never be cancelled."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id, status="succeeded")
    old_prepare_time = datetime.now(UTC) - timedelta(minutes=31)
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="CONFIRMED",
        prepare_time=old_prepare_time,
        click_trans_id=9003,
    )

    await click_timeout.run_click_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "CONFIRMED"

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "succeeded"


async def test_no_stale_transactions_is_a_silent_no_op(db_session: AsyncSession) -> None:
    """An empty sweep must not raise -- covers the early-return path when the
    listing query finds nothing."""
    await click_timeout.run_click_timeout()


async def test_stale_prepared_transaction_with_shared_succeeded_payment_leaves_payment_alone(
    db_session: AsyncSession,
) -> None:
    """Money-safety regression: ``click.service._ensure_payment`` reuses one
    order's pending payment across every ``/prepare`` call for that order (a
    customer retrying checkout). If a sibling transaction already confirmed
    that shared payment (-> succeeded, order -> paid), a stale PREPARED
    transaction still pointing at it must be cancelled WITHOUT cancelling the
    now-succeeded payment out from under the paid order."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id, status="succeeded")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    order.status = "paid"
    await db_session.commit()
    old_prepare_time = datetime.now(UTC) - timedelta(minutes=31)
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="PREPARED",
        prepare_time=old_prepare_time,
        click_trans_id=9004,
    )

    await click_timeout.run_click_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "CANCELLED"

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "succeeded"  # NOT cancelled -- a sibling owns it

    order = (
        await db_session.execute(
            select(Order).where(Order.id == order_id).execution_options(**_FRESH)
        )
    ).scalar_one()
    assert order.status == "paid"  # NOT reverted
