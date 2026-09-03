"""Integration tests for the ``uzum_transactions`` data model and the Uzum
Bank Merchant API service handlers.

Model tests cover: inserting an ``UzumTransaction`` against the real
(testcontainers) Postgres, the ``UNIQUE(trans_id)`` guard that makes Uzum's
Merchant API methods idempotent against replays, and the ``status`` CHECK that
only the four legal values (``CREATED``/``CONFIRMED``/``REVERSED``/``FAILED``)
are accepted.

Service tests exercise the five webhook handlers against the same real
Postgres, since the whole point of the module is the money + state-machine +
idempotency guarantees Uzum's sandbox verifies — mirrors
``test_payme_service.py``:

- ``check`` — OK / 10007 unknown order / 10008 already paid / 10009
  cancelled-or-expired.
- ``create`` — CREATED (row inserted, pending payment reused/created) / 10010
  replay / 10010 concurrent INSERT race (IntegrityError recovery) / 10011
  wrong amount / 10007 unknown order.
- ``confirm`` — CONFIRMED + settles payment (order paid) / 10014 unknown /
  10015 on a reversed tx / 10016 already-confirmed replay.
- ``reverse`` — from CREATED (cancel pending, no ledger) / from CONFIRMED
  (ledger reversal) / 10017 when delivered (whole-order and partial-delivery)
  / 10018 replay / 10014 unknown / a CREATED transaction sharing an
  already-``succeeded`` payment with a confirmed sibling leaves that payment
  and the paid order untouched.
- ``status`` — the seven-field shape for CREATED / CONFIRMED / REVERSED.
- ``build_checkout_url`` — the exact open-service URL for a known input.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Importing uzum.service (→ payments.service) directly outside the app trips the
# service ← api.v1 ← wallet.routes import cycle; loading the router package first
# resolves it the same way ``bootstrap.create_app`` does.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.fulfillment.models import Delivery, FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User
from yupay.modules.uzum import service as uzum_svc
from yupay.modules.uzum.errors import UzumError
from yupay.modules.uzum.models import UzumTransaction

pytestmark = pytest.mark.asyncio

SERVICE_ID = 101202


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


# expected tiyin for the default order: 130000.00 UZS * 100 = 13_000_000
EXPECTED_TIYIN = 13_000_000


async def test_uzum_transaction_round_trips(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    txn = UzumTransaction(
        id=new_id(),
        trans_id="686cbf0f0a6e2d3d5c0e1234",
        order_id=order_id,
        amount_tiyin=1_300_000,
        status="CREATED",
        create_time=1_700_000_000_000,
    )
    db_session.add(txn)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(UzumTransaction).where(UzumTransaction.id == txn.id))
    ).scalar_one()
    assert fetched.trans_id == "686cbf0f0a6e2d3d5c0e1234"
    assert fetched.order_id == order_id
    assert fetched.payment_id is None
    assert fetched.amount_tiyin == 1_300_000
    assert fetched.status == "CREATED"
    assert fetched.service_id is None
    assert fetched.create_time == 1_700_000_000_000
    assert fetched.confirm_time is None
    assert fetched.reverse_time is None
    assert fetched.payment_source == {}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_uzum_transaction_rejects_duplicate_trans_id(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_a = await _make_order(db_session, user_id=user_id)
    order_b = await _make_order(db_session, user_id=user_id)

    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="dup-trans-id",
            order_id=order_a,
            amount_tiyin=1_000_000,
            status="CREATED",
        )
    )
    await db_session.flush()

    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="dup-trans-id",
            order_id=order_b,
            amount_tiyin=2_000_000,
            status="CREATED",
        )
    )
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_uzum_transaction_status_check_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id)

    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="bad-status-id",
            order_id=order_id,
            amount_tiyin=1_000_000,
            status="BOGUS",
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()


# ---------- check ----------


async def test_check_ok(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    result = await uzum_svc.check(db_session, service_id=SERVICE_ID, params={"order_id": order_id})
    # data.amount.value carries the charge in SUMS (major units, string) so
    # Uzum's app prefills the amount: 130000.00 UZS -> "130000".
    assert result == {"status": "OK", "data": {"amount": {"value": "130000"}}}


async def test_check_ok_fractional_sum_keeps_decimals(db_session: AsyncSession) -> None:
    # A charge with fractional sums (still an integral tiyin amount) keeps its
    # decimal places in data.amount.value rather than being rounded.
    order_id = await _seed_order(db_session, total_charged=Decimal("130000.50"))
    result = await uzum_svc.check(db_session, service_id=SERVICE_ID, params={"order_id": order_id})
    # The 6-dp column reads back 130000.500000; trailing zeros are stripped.
    assert result == {"status": "OK", "data": {"amount": {"value": "130000.5"}}}


async def test_check_unknown_order_is_10007(db_session: AsyncSession) -> None:
    with pytest.raises(UzumError) as exc:
        await uzum_svc.check(
            db_session, service_id=SERVICE_ID, params={"order_id": str(uuid.uuid4())}
        )
    assert exc.value.code == 10007


async def test_check_missing_order_id_is_10007(db_session: AsyncSession) -> None:
    with pytest.raises(UzumError) as exc:
        await uzum_svc.check(db_session, service_id=SERVICE_ID, params={})
    assert exc.value.code == 10007


async def test_check_paid_order_is_10008(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session, status="paid")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.check(db_session, service_id=SERVICE_ID, params={"order_id": order_id})
    assert exc.value.code == 10008


async def test_check_cancelled_order_is_10009(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session, status="cancelled")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.check(db_session, service_id=SERVICE_ID, params={"order_id": order_id})
    assert exc.value.code == 10009


async def test_check_expired_order_is_10009(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session, status="expired")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.check(db_session, service_id=SERVICE_ID, params={"order_id": order_id})
    assert exc.value.code == 10009


async def test_check_refunded_order_is_10009(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session, status="refunded")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.check(db_session, service_id=SERVICE_ID, params={"order_id": order_id})
    assert exc.value.code == 10009


# ---------- create ----------


async def test_create_creates_created(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    result = await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-create-1",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    assert result["transId"] == "uz-create-1"
    assert result["status"] == "CREATED"
    assert result["amount"] == EXPECTED_TIYIN
    # data is only returned by /check and /status, not /create.
    assert "data" not in result
    assert result["transTime"] > 0

    row = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-create-1")
        )
    ).scalar_one()
    assert row.status == "CREATED"
    assert row.create_time == result["transTime"]
    assert row.service_id == SERVICE_ID
    assert row.amount_tiyin == EXPECTED_TIYIN
    assert row.payment_id is not None

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.provider == "uzum"
    assert payment.status == "pending"
    assert payment.external_id == f"uzum:{order_id}"


async def test_create_replay_same_trans_id_is_10010(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-replay",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    with pytest.raises(UzumError) as exc:
        await uzum_svc.create(
            db_session,
            service_id=SERVICE_ID,
            trans_id="uz-replay",
            params={"order_id": order_id},
            amount=EXPECTED_TIYIN,
        )
    assert exc.value.code == 10010
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(UzumTransaction)
            .where(UzumTransaction.trans_id == "uz-replay")
        )
    ).scalar_one()
    assert count == 1


async def test_create_concurrent_insert_race_recovers_as_10010(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent /create that wins the INSERT race surfaces as 10010.

    The pre-check's ``FOR UPDATE`` locks nothing against a not-yet-existing
    row, so two concurrent first-time ``/create`` calls for the same
    ``trans_id`` can both pass it and both reach the INSERT. This simulates
    that: a competing ``UzumTransaction`` for the same ``trans_id`` is
    already flushed in-transaction (as if another request won the race right
    after our pre-check ran), and ``_load_tx`` is monkeypatched to return
    ``None`` — the honest answer the pre-check would have given at that
    instant — so ``create()`` proceeds into the INSERT. There the real
    ``UNIQUE(trans_id)`` constraint collides, driving the actual
    ``IntegrityError`` → 10010 recovery branch (not a mocked-away one). On
    unfixed code this raises an uncaught ``IntegrityError`` instead.
    """
    order_id = await _seed_order(db_session)
    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="uz-race",
            order_id=order_id,
            payment_id=None,
            amount_tiyin=EXPECTED_TIYIN,
            status="CREATED",
            service_id=SERVICE_ID,
            create_time=uzum_svc.now_ms(),
        )
    )
    await db_session.flush()

    async def _fake_load_tx(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(uzum_svc, "_load_tx", _fake_load_tx)

    with pytest.raises(UzumError) as exc:
        await uzum_svc.create(
            db_session,
            service_id=SERVICE_ID,
            trans_id="uz-race",
            params={"order_id": order_id},
            amount=EXPECTED_TIYIN,
        )
    assert exc.value.code == 10010

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(UzumTransaction)
            .where(UzumTransaction.trans_id == "uz-race")
        )
    ).scalar_one()
    assert count == 1


async def test_create_wrong_amount_is_10011(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    with pytest.raises(UzumError) as exc:
        await uzum_svc.create(
            db_session,
            service_id=SERVICE_ID,
            trans_id="uz-badamt",
            params={"order_id": order_id},
            amount=EXPECTED_TIYIN - 5,
        )
    assert exc.value.code == 10011


async def test_create_non_integral_charge_is_10011(db_session: AsyncSession) -> None:
    # A sub-tiyin charge cannot be expressed as an integer amount — corrupt
    # order data is surfaced as 10011, never silently truncated.
    order_id = await _seed_order(db_session, total_charged=Decimal("130000.005"))
    with pytest.raises(UzumError) as exc:
        await uzum_svc.create(
            db_session,
            service_id=SERVICE_ID,
            trans_id="uz-nonintegral",
            params={"order_id": order_id},
            amount=13_000_000,
        )
    assert exc.value.code == 10011


async def test_create_unknown_order_is_10007(db_session: AsyncSession) -> None:
    with pytest.raises(UzumError) as exc:
        await uzum_svc.create(
            db_session,
            service_id=SERVICE_ID,
            trans_id="uz-noorder",
            params={"order_id": str(uuid.uuid4())},
            amount=EXPECTED_TIYIN,
        )
    assert exc.value.code == 10007


async def test_create_paid_order_is_10008(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session, status="paid")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.create(
            db_session,
            service_id=SERVICE_ID,
            trans_id="uz-create-paid",
            params={"order_id": order_id},
            amount=EXPECTED_TIYIN,
        )
    assert exc.value.code == 10008


async def test_create_reuses_pending_uzum_payment(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="uzum",
            status="pending",
            amount=Decimal("130000.00"),
            currency="UZS",
            external_id=f"uzum:{order_id}",
        )
    )
    await db_session.flush()

    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-reuse",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    row = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-reuse")
        )
    ).scalar_one()
    assert row.payment_id == payment_id
    count = (
        await db_session.execute(
            select(func.count()).select_from(Payment).where(Payment.order_id == order_id)
        )
    ).scalar_one()
    assert count == 1


# ---------- confirm ----------


async def test_confirm_settles_payment(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-confirm-1",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    result = await uzum_svc.confirm(
        db_session, trans_id="uz-confirm-1", payment_source={"paymentSource": "CARD"}
    )
    assert result["transId"] == "uz-confirm-1"
    assert result["status"] == "CONFIRMED"
    assert result["amount"] == EXPECTED_TIYIN
    # data is only returned by /check and /status, not /confirm.
    assert "data" not in result
    assert result["confirmTime"] > 0

    row = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-confirm-1")
        )
    ).scalar_one()
    assert row.status == "CONFIRMED"
    assert row.confirm_time == result["confirmTime"]
    assert row.payment_source == {"paymentSource": "CARD"}

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status != "pending_payment"
    assert order.paid_at is not None


async def test_confirm_unknown_trans_id_is_10014(db_session: AsyncSession) -> None:
    with pytest.raises(UzumError) as exc:
        await uzum_svc.confirm(db_session, trans_id="nope", payment_source={})
    assert exc.value.code == 10014


async def test_confirm_already_confirmed_is_10016(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-confirm-2",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    await uzum_svc.confirm(db_session, trans_id="uz-confirm-2", payment_source={})
    with pytest.raises(UzumError) as exc:
        await uzum_svc.confirm(db_session, trans_id="uz-confirm-2", payment_source={})
    assert exc.value.code == 10016


async def test_confirm_on_reversed_is_10015(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-confirm-3",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    await uzum_svc.reverse(db_session, trans_id="uz-confirm-3")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.confirm(db_session, trans_id="uz-confirm-3", payment_source={})
    assert exc.value.code == 10015


# ---------- reverse ----------


async def test_reverse_from_created_cancels_pending(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-rev-1",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    result = await uzum_svc.reverse(db_session, trans_id="uz-rev-1")
    assert result["transId"] == "uz-rev-1"
    assert result["status"] == "REVERSED"
    assert result["amount"] == EXPECTED_TIYIN
    # data is only returned by /check and /status, not /reverse.
    assert "data" not in result
    assert result["reverseTime"] > 0

    row = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-rev-1")
        )
    ).scalar_one()
    assert row.status == "REVERSED"
    assert row.reverse_time == result["reverseTime"]

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "cancelled"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "pending_payment"


async def test_reverse_from_confirmed_reverses_ledger(db_session: AsyncSession) -> None:
    # Seed a paid (not delivered) order with a succeeded uzum payment and a
    # CONFIRMED transaction directly, so the reverse call takes the ledger
    # -reversal branch rather than the CREATED cancel-pending branch.
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, status="paid")
    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="uzum",
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
            external_id=f"uzum:{order_id}",
        )
    )
    await db_session.flush()
    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="uz-rev-2",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            status="CONFIRMED",
            create_time=1_700_000_000_000,
            confirm_time=1_700_000_100_000,
        )
    )
    await db_session.flush()

    result = await uzum_svc.reverse(db_session, trans_id="uz-rev-2")
    assert result["status"] == "REVERSED"
    assert result["reverseTime"] > 0

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "refunded"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "refunded"


async def test_reverse_when_delivered_is_10017(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, status="delivered")
    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="uzum",
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
        )
    )
    await db_session.flush()
    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="uz-rev-3",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            status="CONFIRMED",
            create_time=1_700_000_000_000,
            confirm_time=1_700_000_100_000,
        )
    )
    await db_session.flush()

    with pytest.raises(UzumError) as exc:
        await uzum_svc.reverse(db_session, trans_id="uz-rev-3")
    assert exc.value.code == 10017
    # Nothing was reversed.
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"
    txn = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-rev-3")
        )
    ).scalar_one()
    assert txn.status == "CONFIRMED"


async def _seed_sku(db: AsyncSession) -> str:
    """Seed a minimal catalog and return a usable ``sku_id``."""
    category = Category(
        id=new_id(),
        slug="games-uzum",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="steam-uzum",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Steam")],
    )
    product = Product(
        id=new_id(),
        slug="steam-wallet-uzum",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Steam Wallet")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="steam-uzum-10",
        denomination="10",
        region="GLOBAL",
        price_usd=Decimal("5.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.flush()
    return sku.id


async def _add_item(db: AsyncSession, *, order_id: str, sku_id: str, state: str) -> str:
    item_id = str(uuid.uuid4())
    db.add(
        OrderItem(
            id=item_id,
            order_id=order_id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("5.00"),
            fulfillment_state=state,
        )
    )
    await db.flush()
    return item_id


async def test_reverse_partial_delivery_is_10017(db_session: AsyncSession) -> None:
    """A multi-item paid order where ONE item is already delivered (the other
    still in progress, so ``order.status == 'fulfilling'``) must refuse the
    ledger reversal with 10017 — otherwise a full reverse would claw back
    money for a code the customer already holds."""
    user_id = await _make_user(db_session)
    # Order rests at ``fulfilling``: not all tasks done, so the coarse
    # {"fulfilled","delivered"} status guard would MISS this.
    order_id = await _make_order(db_session, user_id=user_id, status="fulfilling")
    sku_id = await _seed_sku(db_session)
    delivered_item = await _add_item(
        db_session, order_id=order_id, sku_id=sku_id, state="delivered"
    )
    pending_item = await _add_item(
        db_session, order_id=order_id, sku_id=sku_id, state="in_progress"
    )

    db_session.add_all(
        [
            FulfillmentTask(
                id=str(uuid.uuid4()),
                order_id=order_id,
                order_item_id=delivered_item,
                supplier="mock",
                status="succeeded",
            ),
            FulfillmentTask(
                id=str(uuid.uuid4()),
                order_id=order_id,
                order_item_id=pending_item,
                supplier="mock",
                status="in_progress",
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        Delivery(
            id=str(uuid.uuid4()),
            order_item_id=delivered_item,
            channel="in_app",
            artifact_kind="code",
            artifact={"code": "SEEN"},
        )
    )
    await db_session.flush()

    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="uzum",
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
        )
    )
    await db_session.flush()
    db_session.add(
        UzumTransaction(
            id=new_id(),
            trans_id="uz-rev-partial",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            status="CONFIRMED",
            create_time=1_700_000_000_000,
            confirm_time=1_700_000_100_000,
        )
    )
    await db_session.flush()

    with pytest.raises(UzumError) as exc:
        await uzum_svc.reverse(db_session, trans_id="uz-rev-partial")
    assert exc.value.code == 10017

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "fulfilling"


async def test_reverse_created_with_shared_succeeded_payment_leaves_payment_alone(
    db_session: AsyncSession,
) -> None:
    """Money-safety regression: ``_ensure_payment`` reuses one order's pending
    ``uzum`` payment across every ``/create`` call for that order (a customer
    retrying checkout). If a sibling transaction confirms that shared payment
    (-> succeeded, order -> paid) while THIS transaction is still CREATED, a
    ``/reverse`` on this one must NOT cancel the now-succeeded payment out
    from under the paid order — only this transaction moves to REVERSED."""
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-shared-a",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-shared-b",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    txn_a = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-shared-a")
        )
    ).scalar_one()
    txn_b = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-shared-b")
        )
    ).scalar_one()
    assert txn_a.payment_id == txn_b.payment_id  # sharing the same pending payment

    await uzum_svc.confirm(db_session, trans_id="uz-shared-b", payment_source={})

    result = await uzum_svc.reverse(db_session, trans_id="uz-shared-a")
    assert result["status"] == "REVERSED"

    reloaded_a = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == "uz-shared-a")
        )
    ).scalar_one()
    assert reloaded_a.status == "REVERSED"

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == txn_a.payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"  # NOT cancelled -- a sibling owns it

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    # The order-less-items fixture progresses straight through the
    # in-process fulfilment saga (paid -> fulfilling, same as
    # ``test_confirm_settles_payment``) -- the money-safety property under
    # test is that it stays PAID, never reverted to unpaid/cancelled/refunded.
    assert order.status not in {"pending_payment", "cancelled", "expired", "refunded"}
    assert order.paid_at is not None


async def test_reverse_replay_is_10018(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-rev-4",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    await uzum_svc.reverse(db_session, trans_id="uz-rev-4")
    with pytest.raises(UzumError) as exc:
        await uzum_svc.reverse(db_session, trans_id="uz-rev-4")
    assert exc.value.code == 10018


async def test_reverse_unknown_is_10014(db_session: AsyncSession) -> None:
    with pytest.raises(UzumError) as exc:
        await uzum_svc.reverse(db_session, trans_id="nope")
    assert exc.value.code == 10014


# ---------- status ----------


async def test_status_shape_created(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    created = await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-status-1",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    result = await uzum_svc.status(db_session, trans_id="uz-status-1")
    assert result == {
        "transId": "uz-status-1",
        "status": "CREATED",
        "transTime": created["transTime"],
        "confirmTime": None,
        "reverseTime": None,
        "data": {},
        "amount": EXPECTED_TIYIN,
    }


async def test_status_shape_confirmed(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    created = await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-status-2",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    confirmed = await uzum_svc.confirm(db_session, trans_id="uz-status-2", payment_source={})
    result = await uzum_svc.status(db_session, trans_id="uz-status-2")
    assert result == {
        "transId": "uz-status-2",
        "status": "CONFIRMED",
        "transTime": created["transTime"],
        "confirmTime": confirmed["confirmTime"],
        "reverseTime": None,
        "data": {},
        "amount": EXPECTED_TIYIN,
    }


async def test_status_shape_reversed(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    created = await uzum_svc.create(
        db_session,
        service_id=SERVICE_ID,
        trans_id="uz-status-3",
        params={"order_id": order_id},
        amount=EXPECTED_TIYIN,
    )
    reversed_result = await uzum_svc.reverse(db_session, trans_id="uz-status-3")
    result = await uzum_svc.status(db_session, trans_id="uz-status-3")
    assert result == {
        "transId": "uz-status-3",
        "status": "REVERSED",
        "transTime": created["transTime"],
        "confirmTime": None,
        "reverseTime": reversed_result["reverseTime"],
        "data": {},
        "amount": EXPECTED_TIYIN,
    }


async def test_status_unknown_is_10014(db_session: AsyncSession) -> None:
    with pytest.raises(UzumError) as exc:
        await uzum_svc.status(db_session, trans_id="nope")
    assert exc.value.code == 10014


# ---------- build_checkout_url ----------


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        uzum_service_id=SERVICE_ID,
        uzum_open_service_url="https://uzumbank.uz/open-service",
    )


async def test_build_checkout_url_no_return(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uzum_svc, "get_settings", _fake_settings)
    url = uzum_svc.build_checkout_url(
        order_id="ORDER-1", amount_tiyin=EXPECTED_TIYIN, return_url=None
    )
    expected = "https://uzumbank.uz/open-service?" + urlencode(
        {"serviceId": SERVICE_ID, "orderId": "ORDER-1"}
    )
    assert url == expected


async def test_build_checkout_url_with_return(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uzum_svc, "get_settings", _fake_settings)
    url = uzum_svc.build_checkout_url(
        order_id="ORDER-1",
        amount_tiyin=EXPECTED_TIYIN,
        return_url="https://yupay.uz/return",
    )
    expected = "https://uzumbank.uz/open-service?" + urlencode(
        {
            "serviceId": SERVICE_ID,
            "orderId": "ORDER-1",
            "redirectUrl": "https://yupay.uz/return",
        }
    )
    assert url == expected
