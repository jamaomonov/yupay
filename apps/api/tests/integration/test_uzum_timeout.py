"""Integration tests for the Uzum 30-minute unconfirmed-transaction sweep
(Task 7).

Uzum's Merchant API contract has ``/create`` register a pending (``CREATED``)
transaction that the buyer is expected to complete via ``/confirm`` within
Uzum's own SLA window (spec §10: 30 minutes). If Uzum never calls back with
``/confirm`` or ``/reverse`` (buyer abandonment, dropped callback), the
transaction — and the ``payments`` row it backs — would sit ``pending``
forever. These tests exercise
``yupay_scheduler.jobs.uzum_timeout.run_uzum_timeout`` end to end against a
directly-seeded ``Order`` + ``Payment`` + ``UzumTransaction`` (bypassing
checkout entirely), mirroring ``test_payme_timeout.py``'s own-session
redirection and ``test_uzum_service.py``'s direct-seeding style.

No real sleeping: ``create_time`` (Uzum epoch-ms) is seeded directly at a
clearly-old or clearly-recent value rather than waiting out
``uzum_timeout.TIMEOUT_MS`` in real time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Importing yupay.api.v1 first avoids the payments.service <-> wallet.routes
# <-> api.v1 import cycle -- see uzum_timeout.py's module docstring and
# test_uzum_service.py, which hits the exact same trap.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.uzum.models import UzumTransaction
from yupay_scheduler.jobs import uzum_timeout

pytestmark = pytest.mark.asyncio

_MINUTE_MS = 60_000


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """The job never uses the request-scoped ``db_session`` fixture -- in
    production it resolves its own factory via ``get_session_factory()``.
    Point that at the truncated test container so the job's sessions and the
    test's assertion session (``db_session``) see the same database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(uzum_timeout, "get_session_factory", lambda: factory)


async def _seed_order(db: AsyncSession, *, total_charged: Decimal = Decimal("130000.00")) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=None,
            guest_email="uzum-timeout@example.test",
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
            provider="uzum",
            status=status,
            amount=Decimal("130000.00"),
            currency="UZS",
            external_id=f"uzum:{order_id}",
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
    create_time: int,
) -> str:
    txn_id = new_id()
    db.add(
        UzumTransaction(
            id=txn_id,
            trans_id=f"uzum-{txn_id}",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=13_000_000,
            status=status,
            create_time=create_time,
        )
    )
    await db.commit()
    return txn_id


_FRESH = {"populate_existing": True}


async def _reload_txn(db: AsyncSession, txn_id: str) -> UzumTransaction:
    return (
        await db.execute(
            select(UzumTransaction).where(UzumTransaction.id == txn_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def _reload_payment(db: AsyncSession, payment_id: str) -> Payment:
    return (
        await db.execute(
            select(Payment).where(Payment.id == payment_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def test_stale_created_transaction_is_failed(db_session: AsyncSession) -> None:
    """A CREATED transaction whose create_time is 31 minutes old is failed
    (status -> FAILED), and its backing pending payment -> cancelled."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id)
    old_create_time = uzum_timeout.now_ms() - 31 * _MINUTE_MS
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="CREATED",
        create_time=old_create_time,
    )

    await uzum_timeout.run_uzum_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "FAILED"
    assert txn.confirm_time is None
    assert txn.reverse_time is None

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "cancelled"


async def test_fresh_created_transaction_is_untouched(db_session: AsyncSession) -> None:
    """A CREATED transaction only 5 minutes old is well within the 30-minute
    timeout and must be left completely alone."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id)
    recent_create_time = uzum_timeout.now_ms() - 5 * _MINUTE_MS
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="CREATED",
        create_time=recent_create_time,
    )

    await uzum_timeout.run_uzum_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "CREATED"

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "pending"


async def test_confirmed_transaction_is_never_touched(db_session: AsyncSession) -> None:
    """A CONFIRMED transaction is never touched by the timeout sweep, no
    matter how old create_time is -- only CREATED is in scope. This is the
    money-safety invariant: a settled payment must never be cancelled."""
    order_id = await _seed_order(db_session)
    payment_id = await _seed_payment(db_session, order_id=order_id, status="succeeded")
    old_create_time = uzum_timeout.now_ms() - 31 * _MINUTE_MS
    txn_id = await _seed_transaction(
        db_session,
        order_id=order_id,
        payment_id=payment_id,
        status="CONFIRMED",
        create_time=old_create_time,
    )

    await uzum_timeout.run_uzum_timeout()

    txn = await _reload_txn(db_session, txn_id)
    assert txn.status == "CONFIRMED"

    payment = await _reload_payment(db_session, payment_id)
    assert payment.status == "succeeded"


async def test_no_stale_transactions_is_a_silent_no_op(db_session: AsyncSession) -> None:
    """An empty sweep must not raise -- covers the early-return path when the
    listing query finds nothing."""
    await uzum_timeout.run_uzum_timeout()
