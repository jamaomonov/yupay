"""Integration tests for the ``click_transactions`` data model and the Click
Shop API service handlers.

Model tests cover: inserting a ``ClickTransaction`` against the real
(testcontainers) Postgres and confirming ``merchant_prepare_id`` is DB-assigned
(IDENTITY, not app-supplied), the ``UNIQUE(click_trans_id, service_id)`` guard
that makes ``/prepare``/``/complete`` idempotent against replays, and the
``status`` CHECK that only the three legal values (``PREPARED``/``CONFIRMED``/
``CANCELLED``) are accepted.

Service tests exercise ``prepare``/``complete``/``cancel``/
``build_checkout_url`` against the same real Postgres, mirroring
``test_uzum_service.py``:

- ``prepare`` — PREPARED (row inserted, ``merchant_prepare_id`` assigned,
  pending payment created under the right provider) / replay returns the same
  ``merchant_prepare_id`` / concurrent-INSERT race recovers to the winner's id
  / -2 wrong amount / -5 unknown order / -4 already paid / -9
  cancelled/expired/refunded.
- ``complete`` — CONFIRMED + settles the payment (order paid) / -6 unknown or
  mismatched ``merchant_prepare_id`` / -4 replay on CONFIRMED / -9 on
  CANCELLED / -2 amount mismatch.
- ``cancel`` — PREPARED -> CANCELLED + cancels the pending payment; looked up
  by either ``merchant_prepare_id`` or ``(click_trans_id, service_id)``; a
  CONFIRMED transaction is left entirely alone; a PREPARED transaction sharing
  an already-confirmed sibling's payment is cancelled itself but the shared
  (succeeded) payment is left untouched (money-safety guard, carried forward
  from the Uzum final review).
- ``build_checkout_url`` — the exact pay URL for both the web and mini-app
  services.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Importing click.service (→ payments.service → wallet.api) directly outside the
# app trips the service ← api.v1 ← wallet.routes import cycle; loading the router
# package first resolves it the same way ``bootstrap.create_app`` does (mirrors
# the same guard in ``test_uzum_service.py``).
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core import config as cfg
from yupay.core.clock import now as clock_now
from yupay.core.ids import new_id
from yupay.modules.click import service as click_svc
from yupay.modules.click.errors import ClickError
from yupay.modules.click.models import ClickTransaction
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

SERVICE_ID = 108149
BOT_SERVICE_ID = 108150


async def _make_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    return user_id


async def _make_order(
    db: AsyncSession,
    *,
    user_id: str,
    status: str = "pending_payment",
    total_charged: Decimal = Decimal("130000.00"),
) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status=status,
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=total_charged,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db.flush()
    return order_id


async def _seed_order(
    db: AsyncSession,
    *,
    status: str = "pending_payment",
    total_charged: Decimal = Decimal("130000.00"),
) -> str:
    user_id = await _make_user(db)
    return await _make_order(db, user_id=user_id, status=status, total_charged=total_charged)


# A whole-so'm amount, so ``amount == str(A)`` on the wire (Click's own ``amount``
# field arrives as a raw string) round-trips exactly through ``Decimal``.
TOTAL_CHARGED = Decimal("130000.00")
AMOUNT_STR = str(TOTAL_CHARGED)


@pytest.fixture
def _click_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure both Click services + the merchant id ``prepare``/``complete``/
    ``build_checkout_url`` need (``get_settings`` is process-lifetime cached via
    ``lru_cache`` — cleared on both sides so this doesn't leak into other tests,
    mirroring the fixture in ``test_click_signature.py``)."""
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", str(SERVICE_ID))
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", str(BOT_SERVICE_ID))
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "web-secret-abc")
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", "bot-secret-xyz")
    monkeypatch.setenv("CLICK_MERCHANT_ID", "63276")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def test_click_transaction_round_trips(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    txn = ClickTransaction(
        id=new_id(),
        click_trans_id=4_294_967_295,
        service_id=SERVICE_ID,
        order_id=order_id,
        amount=Decimal("130000.000000"),
        status="PREPARED",
    )
    db_session.add(txn)
    await db_session.flush()
    await db_session.refresh(txn)

    assert isinstance(txn.merchant_prepare_id, int)
    assert txn.merchant_prepare_id > 0

    fetched = (
        await db_session.execute(select(ClickTransaction).where(ClickTransaction.id == txn.id))
    ).scalar_one()
    assert fetched.merchant_prepare_id == txn.merchant_prepare_id
    assert fetched.click_trans_id == 4_294_967_295
    assert fetched.service_id == SERVICE_ID
    assert fetched.order_id == order_id
    assert fetched.payment_id is None
    assert fetched.amount == Decimal("130000.000000")
    assert fetched.status == "PREPARED"
    assert fetched.click_paydoc_id is None
    assert fetched.prepare_time is None
    assert fetched.complete_time is None
    assert fetched.cancel_time is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_click_transaction_rejects_duplicate_trans_service(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_a = await _make_order(db_session, user_id=user_id)
    order_b = await _make_order(db_session, user_id=user_id)

    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=111,
            service_id=SERVICE_ID,
            order_id=order_a,
            amount=Decimal("10000.000000"),
            status="PREPARED",
        )
    )
    await db_session.flush()

    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=111,
            service_id=SERVICE_ID,
            order_id=order_b,
            amount=Decimal("20000.000000"),
            status="PREPARED",
        )
    )
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_click_transaction_status_check_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=222,
            service_id=SERVICE_ID,
            order_id=order_id,
            amount=Decimal("10000.000000"),
            status="BOGUS",
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


# ---------- prepare ----------


async def test_prepare_creates_prepared(db_session: AsyncSession, _click_env: None) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)

    result = await click_svc.prepare(
        db_session,
        click_trans_id=1001,
        service_id=SERVICE_ID,
        click_paydoc_id=5001,
        merchant_trans_id=order_id,
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:00:00",
    )

    assert result["click_trans_id"] == 1001
    assert result["merchant_trans_id"] == order_id
    assert isinstance(result["merchant_prepare_id"], int)
    assert result["merchant_prepare_id"] > 0
    assert result["error"] == 0
    assert result["error_note"] == "Success"

    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 1001)
        )
    ).scalar_one()
    assert row.status == "PREPARED"
    assert row.merchant_prepare_id == result["merchant_prepare_id"]
    assert row.click_paydoc_id == 5001
    assert row.amount == TOTAL_CHARGED
    assert row.prepare_time is not None
    assert row.payment_id is not None

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.provider == "click"
    assert payment.status == "pending"
    assert payment.external_id == f"click:{order_id}"


async def test_prepare_replay_returns_same_prepare_id(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    kwargs: dict[str, Any] = {
        "click_trans_id": 1002,
        "service_id": SERVICE_ID,
        "click_paydoc_id": 5002,
        "merchant_trans_id": order_id,
        "amount": AMOUNT_STR,
        "sign_time": "2026-07-23 10:00:00",
    }
    first = await click_svc.prepare(db_session, **kwargs)
    second = await click_svc.prepare(db_session, **kwargs)

    assert second["merchant_prepare_id"] == first["merchant_prepare_id"]
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ClickTransaction)
            .where(ClickTransaction.click_trans_id == 1002)
        )
    ).scalar_one()
    assert count == 1


async def test_prepare_concurrent_insert_race_returns_winners_id(
    db_session: AsyncSession, _click_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent /prepare that wins the INSERT race must still resolve to
    ONE idempotent success — Click's replay contract expects the same
    ``merchant_prepare_id`` back, not an error.

    The pre-check's ``FOR UPDATE`` locks nothing against a not-yet-existing
    row, so two concurrent first-time ``/prepare`` calls for the same
    ``(click_trans_id, service_id)`` can both pass it and both reach the
    INSERT. This simulates that: a competing ``ClickTransaction`` is already
    flushed in-transaction (as if another request won the race right after
    our pre-check ran), and ``_load_txn_by_click`` is monkeypatched to lie
    (return ``None``) on its FIRST call only — the honest answer the
    pre-check would have given at that instant — so ``prepare()`` proceeds
    into the INSERT, where the real ``UNIQUE(click_trans_id, service_id)``
    collides, driving the actual ``IntegrityError`` -> re-read recovery
    branch (not a mocked-away one). The SECOND call (the recovery re-read)
    uses the real implementation and finds the winner's row. On unfixed code
    this raises an uncaught ``IntegrityError`` instead.
    """
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    winner_payment_id = new_id()
    db_session.add(
        Payment(
            id=winner_payment_id,
            order_id=order_id,
            provider="click",
            status="pending",
            amount=TOTAL_CHARGED,
            currency="UZS",
            external_id=f"click:{order_id}",
        )
    )
    await db_session.flush()
    db_session.add(
        ClickTransaction(
            id=new_id(),
            click_trans_id=1003,
            service_id=SERVICE_ID,
            order_id=order_id,
            payment_id=winner_payment_id,
            amount=TOTAL_CHARGED,
            status="PREPARED",
            prepare_time=clock_now(),
        )
    )
    await db_session.flush()

    real_load = click_svc._load_txn_by_click
    call_count = {"n": 0}

    async def _fake_load_txn_by_click(*args: object, **kwargs: object) -> ClickTransaction | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return await real_load(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(click_svc, "_load_txn_by_click", _fake_load_txn_by_click)

    result = await click_svc.prepare(
        db_session,
        click_trans_id=1003,
        service_id=SERVICE_ID,
        click_paydoc_id=5003,
        merchant_trans_id=order_id,
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:00:00",
    )

    winner = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 1003)
        )
    ).scalar_one()
    assert result["merchant_prepare_id"] == winner.merchant_prepare_id
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ClickTransaction)
            .where(ClickTransaction.click_trans_id == 1003)
        )
    ).scalar_one()
    assert count == 1


async def test_prepare_wrong_amount_is_minus2(db_session: AsyncSession, _click_env: None) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1004,
            service_id=SERVICE_ID,
            click_paydoc_id=5004,
            merchant_trans_id=order_id,
            amount=str(TOTAL_CHARGED - Decimal("1.00")),
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -2


async def test_prepare_unknown_order_is_minus5(db_session: AsyncSession, _click_env: None) -> None:
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1005,
            service_id=SERVICE_ID,
            click_paydoc_id=5005,
            merchant_trans_id=str(uuid.uuid4()),
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -5


async def test_prepare_blank_merchant_trans_id_is_minus5(
    db_session: AsyncSession, _click_env: None
) -> None:
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1005,
            service_id=SERVICE_ID,
            click_paydoc_id=5005,
            merchant_trans_id="",
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -5


async def test_prepare_unknown_service_id_is_minus1(
    db_session: AsyncSession, _click_env: None
) -> None:
    """``_provider_for_service`` is a defensive fallback: in practice the route
    layer already rejects an unknown ``service_id`` while verifying the
    signature, but a service_id that matches neither configured service must
    still fail closed here rather than silently pick a provider."""
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1099,
            service_id=999_999,
            click_paydoc_id=5099,
            merchant_trans_id=order_id,
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -1


async def test_prepare_already_paid_order_is_minus4(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, status="paid", total_charged=TOTAL_CHARGED)
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1006,
            service_id=SERVICE_ID,
            click_paydoc_id=5006,
            merchant_trans_id=order_id,
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -4


async def test_prepare_cancelled_order_is_minus9(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, status="cancelled", total_charged=TOTAL_CHARGED)
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1007,
            service_id=SERVICE_ID,
            click_paydoc_id=5007,
            merchant_trans_id=order_id,
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -9


async def test_prepare_expired_order_is_minus9(db_session: AsyncSession, _click_env: None) -> None:
    order_id = await _seed_order(db_session, status="expired", total_charged=TOTAL_CHARGED)
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1008,
            service_id=SERVICE_ID,
            click_paydoc_id=5008,
            merchant_trans_id=order_id,
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -9


async def test_prepare_refunded_order_is_minus9(db_session: AsyncSession, _click_env: None) -> None:
    order_id = await _seed_order(db_session, status="refunded", total_charged=TOTAL_CHARGED)
    with pytest.raises(ClickError) as exc:
        await click_svc.prepare(
            db_session,
            click_trans_id=1009,
            service_id=SERVICE_ID,
            click_paydoc_id=5009,
            merchant_trans_id=order_id,
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:00:00",
        )
    assert exc.value.code == -9


async def test_prepare_bot_service_uses_click_miniapp_provider(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    result = await click_svc.prepare(
        db_session,
        click_trans_id=1010,
        service_id=BOT_SERVICE_ID,
        click_paydoc_id=5010,
        merchant_trans_id=order_id,
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:00:00",
    )
    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 1010)
        )
    ).scalar_one()
    assert row.merchant_prepare_id == result["merchant_prepare_id"]
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.provider == "click_miniapp"


# ---------- complete ----------


async def _prepared_txn(
    db: AsyncSession, *, order_id: str, click_trans_id: int, click_paydoc_id: int = 6000
) -> dict[str, Any]:
    return await click_svc.prepare(
        db,
        click_trans_id=click_trans_id,
        service_id=SERVICE_ID,
        click_paydoc_id=click_paydoc_id,
        merchant_trans_id=order_id,
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:00:00",
    )


async def test_complete_settles_payment(db_session: AsyncSession, _click_env: None) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=2001)

    result = await click_svc.complete(
        db_session,
        click_trans_id=2001,
        service_id=SERVICE_ID,
        merchant_trans_id=order_id,
        merchant_prepare_id=prepared["merchant_prepare_id"],
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:05:00",
    )

    assert result["click_trans_id"] == 2001
    assert result["merchant_trans_id"] == order_id
    assert result["merchant_confirm_id"] == prepared["merchant_prepare_id"]
    assert result["error"] == 0
    assert result["error_note"] == "Success"

    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 2001)
        )
    ).scalar_one()
    assert row.status == "CONFIRMED"
    assert row.complete_time is not None

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status != "pending_payment"
    assert order.paid_at is not None


async def test_complete_unknown_prepare_id_is_minus6(
    db_session: AsyncSession, _click_env: None
) -> None:
    with pytest.raises(ClickError) as exc:
        await click_svc.complete(
            db_session,
            click_trans_id=2002,
            service_id=SERVICE_ID,
            merchant_trans_id=str(uuid.uuid4()),
            merchant_prepare_id=999_999_999,
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:05:00",
        )
    assert exc.value.code == -6


async def test_complete_replay_on_confirmed_is_minus4(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=2003)
    complete_kwargs: dict[str, Any] = {
        "click_trans_id": 2003,
        "service_id": SERVICE_ID,
        "merchant_trans_id": order_id,
        "merchant_prepare_id": prepared["merchant_prepare_id"],
        "amount": AMOUNT_STR,
        "sign_time": "2026-07-23 10:05:00",
    }
    await click_svc.complete(db_session, **complete_kwargs)

    with pytest.raises(ClickError) as exc:
        await click_svc.complete(db_session, **complete_kwargs)
    assert exc.value.code == -4


async def test_complete_on_cancelled_is_minus9(db_session: AsyncSession, _click_env: None) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=2004)
    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])

    with pytest.raises(ClickError) as exc:
        await click_svc.complete(
            db_session,
            click_trans_id=2004,
            service_id=SERVICE_ID,
            merchant_trans_id=order_id,
            merchant_prepare_id=prepared["merchant_prepare_id"],
            amount=AMOUNT_STR,
            sign_time="2026-07-23 10:05:00",
        )
    assert exc.value.code == -9


async def test_complete_amount_mismatch_is_minus2(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=2005)

    with pytest.raises(ClickError) as exc:
        await click_svc.complete(
            db_session,
            click_trans_id=2005,
            service_id=SERVICE_ID,
            merchant_trans_id=order_id,
            merchant_prepare_id=prepared["merchant_prepare_id"],
            amount=str(TOTAL_CHARGED - Decimal("1.00")),
            sign_time="2026-07-23 10:05:00",
        )
    assert exc.value.code == -2


# ---------- cancel ----------


async def test_cancel_from_prepared_cancels_pending_payment(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=3001)

    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])

    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3001)
        )
    ).scalar_one()
    assert row.status == "CANCELLED"
    assert row.cancel_time is not None

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "cancelled"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "pending_payment"


async def test_cancel_by_click_trans_id_and_service_id(
    db_session: AsyncSession, _click_env: None
) -> None:
    """The ``/prepare`` negative-``error`` path only ever has
    ``(click_trans_id, service_id)`` to identify the transaction (Click hasn't
    echoed a ``merchant_prepare_id`` back yet at that point in the flow)."""
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    await _prepared_txn(db_session, order_id=order_id, click_trans_id=3002)

    await click_svc.cancel(db_session, click_trans_id=3002, service_id=SERVICE_ID)

    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3002)
        )
    ).scalar_one()
    assert row.status == "CANCELLED"


async def test_cancel_requires_a_lookup_key(db_session: AsyncSession, _click_env: None) -> None:
    with pytest.raises(ValueError, match="merchant_prepare_id"):
        await click_svc.cancel(db_session)


async def test_cancel_already_cancelled_is_idempotent_noop(
    db_session: AsyncSession, _click_env: None
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=3003)
    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])

    # Second cancel on the same (now CANCELLED) transaction must not raise or
    # touch anything further.
    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])

    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3003)
        )
    ).scalar_one()
    assert row.status == "CANCELLED"


async def test_cancel_confirmed_transaction_leaves_payment_and_status_alone(
    db_session: AsyncSession, _click_env: None
) -> None:
    """Money-safety guard: Click v1 has no merchant-initiated refund, so a
    settled (``CONFIRMED``) transaction must never be touched by ``cancel()``
    — not its payment, not its own status."""
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    prepared = await _prepared_txn(db_session, order_id=order_id, click_trans_id=3004)
    await click_svc.complete(
        db_session,
        click_trans_id=3004,
        service_id=SERVICE_ID,
        merchant_trans_id=order_id,
        merchant_prepare_id=prepared["merchant_prepare_id"],
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:05:00",
    )

    await click_svc.cancel(db_session, merchant_prepare_id=prepared["merchant_prepare_id"])

    row = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3004)
        )
    ).scalar_one()
    assert row.status == "CONFIRMED"

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.paid_at is not None


async def test_cancel_shared_payment_confirmed_sibling_leaves_payment_alone(
    db_session: AsyncSession, _click_env: None
) -> None:
    """Money-safety regression: ``_ensure_payment`` reuses one order's pending
    ``click`` payment across every ``/prepare`` call for that order (a
    customer retrying checkout). If a sibling transaction confirms that
    shared payment (-> succeeded, order -> paid) while THIS transaction is
    still PREPARED, cancelling THIS one must NOT cancel the now-succeeded
    payment out from under the paid order — only this transaction moves to
    CANCELLED."""
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    txn_a = await _prepared_txn(db_session, order_id=order_id, click_trans_id=3005)
    txn_b = await _prepared_txn(db_session, order_id=order_id, click_trans_id=3006)

    row_a = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3005)
        )
    ).scalar_one()
    row_b = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3006)
        )
    ).scalar_one()
    assert row_a.payment_id == row_b.payment_id  # sharing the same pending payment

    await click_svc.complete(
        db_session,
        click_trans_id=3006,
        service_id=SERVICE_ID,
        merchant_trans_id=order_id,
        merchant_prepare_id=txn_b["merchant_prepare_id"],
        amount=AMOUNT_STR,
        sign_time="2026-07-23 10:05:00",
    )

    await click_svc.cancel(db_session, merchant_prepare_id=txn_a["merchant_prepare_id"])

    reloaded_a = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == 3005)
        )
    ).scalar_one()
    assert reloaded_a.status == "CANCELLED"

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row_a.payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"  # NOT cancelled -- sibling b owns it

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status not in {"pending_payment", "cancelled", "expired", "refunded"}
    assert order.paid_at is not None


# ---------- build_checkout_url ----------


async def test_build_checkout_url_click_web(_click_env: None) -> None:
    url = click_svc.build_checkout_url(
        provider="click",
        order_id="ORDER-1",
        amount=TOTAL_CHARGED,
        return_url="https://yupay.uz/return",
    )
    expected = "https://my.click.uz/services/pay?" + urlencode(
        {
            "service_id": SERVICE_ID,
            "merchant_id": 63276,
            "amount": TOTAL_CHARGED,
            "transaction_param": "ORDER-1",
            "return_url": "https://yupay.uz/return",
        }
    )
    assert url == expected


async def test_build_checkout_url_click_miniapp(_click_env: None) -> None:
    url = click_svc.build_checkout_url(
        provider="click_miniapp",
        order_id="ORDER-1",
        amount=TOTAL_CHARGED,
        return_url="https://t.me/yupayapp_bot",
    )
    expected = "https://my.click.uz/services/pay?" + urlencode(
        {
            "service_id": BOT_SERVICE_ID,
            "merchant_id": 63276,
            "amount": TOTAL_CHARGED,
            "transaction_param": "ORDER-1",
            "return_url": "https://t.me/yupayapp_bot",
        }
    )
    assert url == expected


async def test_build_checkout_url_unknown_provider_raises(_click_env: None) -> None:
    with pytest.raises(ValueError, match="unknown click provider"):
        click_svc.build_checkout_url(
            provider="octo",
            order_id="ORDER-1",
            amount=TOTAL_CHARGED,
            return_url="https://yupay.uz/return",
        )
