"""Integration tests for the Payme 12h auto-cancel sweep (Task 8).

Payme's ``CreateTransaction`` registers a pending (state ``1``) transaction
that the buyer is expected to complete on Payme's own checkout UI. If Payme
never calls back with ``PerformTransaction``/``CancelTransaction`` (buyer
abandonment), the transaction — and the ``payments`` row it backs — would
sit ``pending`` forever. These tests exercise
``yupay_scheduler.jobs.payme_timeout.run_payme_timeout`` end to end against
a directly-seeded ``Order`` + ``Payment`` + ``PaymeTransaction`` (bypassing
checkout entirely), mirroring ``test_waxpeer_reconcile.py``'s own-session
redirection and ``test_payme_service.py``'s direct-seeding style.

No real sleeping: ``create_time`` (Payme epoch-ms) is seeded directly at a
clearly-old or clearly-recent value rather than waiting out
``payme_timeout.TIMEOUT_MS`` in real time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Importing yupay.api.v1 first avoids the payments.service <-> wallet.routes
# <-> api.v1 import cycle -- see payme_timeout.py's module docstring and
# test_payme_service.py, which hits the exact same trap.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.payments.models import Payment
from yupay_scheduler.jobs import payme_timeout

pytestmark = pytest.mark.asyncio

_HOUR_MS = 3_600_000


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """The job never uses the request-scoped ``db_session`` fixture -- in
    production it resolves its own factory via ``get_session_factory()``.
    Point that at the truncated test container so the job's sessions and the
    test's assertion session (``db_session``) see the same database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(payme_timeout, "get_session_factory", lambda: factory)


async def _seed_order(db: AsyncSession, *, total_charged: Decimal = Decimal("50000.00")) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=None,
            guest_email="timeout@example.test",
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("4.00"),
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
            provider="payme",
            status=status,
            amount=Decimal("50000.00"),
            currency="UZS",
            external_id=f"payme:{order_id}",
        )
    )
    await db.flush()
    return payment_id


async def _seed_transaction(
    db: AsyncSession,
    *,
    order_id: str,
    payment_id: str | None,
    state: int,
    create_time: int,
) -> str:
    txn_id = new_id()
    db.add(
        PaymeTransaction(
            id=txn_id,
            payme_id=f"payme-{txn_id}",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=5_000_000,
            state=state,
            create_time=create_time,
        )
    )
    await db.commit()
    return txn_id


_FRESH = {"populate_existing": True}


async def _reload_txn(db: AsyncSession, txn_id: str) -> PaymeTransaction:
    return (
        await db.execute(
            select(PaymeTransaction)
            .where(PaymeTransaction.id == txn_id)
            .execution_options(**_FRESH)
        )
    ).scalar_one()


async def _reload_payment(db: AsyncSession, payment_id: str) -> Payment:
    return (
        await db.execute(
            select(Payment).where(Payment.id == payment_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def test_stale_pending_transaction_is_cancelled(db_session: AsyncSession) -> None:
    """A state-1 transaction whose create_time is 13h old is cancelled to
    state -1/reason 4/cancel_time set, and its backing payment -> cancelled."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id)
    old_create_time = payme_timeout.now_ms() - 13 * _HOUR_MS
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        state=1,
        create_time=old_create_time,
    )

    before = payme_timeout.now_ms()
    await payme_timeout.run_payme_timeout()
    after = payme_timeout.now_ms()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.state == -1
    assert txn.reason == 4
    assert before <= txn.cancel_time <= after

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "cancelled"


async def test_recent_pending_transaction_is_untouched(db_session: AsyncSession) -> None:
    """A state-1 transaction only 1h old is well within the 12h timeout and
    must be left completely alone."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id)
    recent_create_time = payme_timeout.now_ms() - 1 * _HOUR_MS
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        state=1,
        create_time=recent_create_time,
    )

    await payme_timeout.run_payme_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.state == 1
    assert txn.reason is None
    assert txn.cancel_time == 0

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "pending"


async def test_performed_transaction_is_untouched(db_session: AsyncSession) -> None:
    """A state-2 (performed) transaction is never touched by the timeout
    sweep, no matter how old create_time is -- only state 1 is in scope."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id, status="succeeded")
    old_create_time = payme_timeout.now_ms() - 13 * _HOUR_MS
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        state=2,
        create_time=old_create_time,
    )

    await payme_timeout.run_payme_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.state == 2
    assert txn.reason is None
    assert txn.cancel_time == 0

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "succeeded"


async def test_no_stale_transactions_is_a_silent_no_op(db_session: AsyncSession) -> None:
    """An empty sweep must not raise -- covers the early-return path when the
    listing query finds nothing."""
    await payme_timeout.run_payme_timeout()
