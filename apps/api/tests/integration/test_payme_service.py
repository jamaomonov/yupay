"""Integration tests for the Payme (Paycom) Merchant API service handlers.

These exercise the seven method handlers against the real (testcontainers)
Postgres, since the whole point of the module is the money + state-machine +
idempotency guarantees Payme's sandbox verifies:

- ``check_perform_transaction`` — allow / -31050 / -31051 / -31001.
- ``create_transaction`` — creates state 1, is idempotent on replay (one row),
  and refuses a second active transaction on the same order (-31099).
- ``perform_transaction`` — walks to state 2 + settles the payment (order paid),
  idempotent replay.
- ``cancel_transaction`` — state 1 → -1 (pending cancel), state 2 → -2 (refund
  reversal), -31007 when the order is already delivered.
- ``check_transaction`` — the six-field response shape.
- ``get_statement`` — the create_time window.
- ``set_fiscal_data`` — stores the receipt keyed by type.
- ``build_checkout_url`` — the exact base64 payload for a known input.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Importing payme.service (→ payments.service) directly outside the app trips the
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
from yupay.modules.payme import service as payme_svc
from yupay.modules.payme.errors import PaymeError
from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


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


# ---------- check_perform_transaction ----------


async def test_check_perform_allows_valid(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    result = await payme_svc.check_perform_transaction(
        db_session, amount=EXPECTED_TIYIN, account={"order_id": order_id}
    )
    assert result == {"allow": True}


async def test_check_perform_wrong_amount_is_31001(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    with pytest.raises(PaymeError) as exc:
        await payme_svc.check_perform_transaction(
            db_session, amount=EXPECTED_TIYIN + 1, account={"order_id": order_id}
        )
    assert exc.value.code == -31001


async def test_check_perform_unknown_account_is_31050(db_session: AsyncSession) -> None:
    with pytest.raises(PaymeError) as exc:
        await payme_svc.check_perform_transaction(
            db_session, amount=EXPECTED_TIYIN, account={"order_id": str(uuid.uuid4())}
        )
    assert exc.value.code == -31050


async def test_check_perform_missing_account_is_31050(db_session: AsyncSession) -> None:
    with pytest.raises(PaymeError) as exc:
        await payme_svc.check_perform_transaction(db_session, amount=EXPECTED_TIYIN, account={})
    assert exc.value.code == -31050


async def test_check_perform_non_pending_order_is_31051(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session, status="paid")
    with pytest.raises(PaymeError) as exc:
        await payme_svc.check_perform_transaction(
            db_session, amount=EXPECTED_TIYIN, account={"order_id": order_id}
        )
    assert exc.value.code == -31051


# ---------- create_transaction ----------


async def test_create_transaction_creates_state_1(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    result = await payme_svc.create_transaction(
        db_session,
        payme_id="pt-create-1",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    assert result["state"] == 1
    assert result["create_time"] == 1_700_000_000_000
    row = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-create-1")
        )
    ).scalar_one()
    assert result["transaction"] == row.id
    assert row.amount_tiyin == EXPECTED_TIYIN
    assert row.payment_id is not None
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.provider == "payme"
    assert payment.status == "pending"


async def test_create_transaction_replay_is_idempotent_one_row(
    db_session: AsyncSession,
) -> None:
    order_id = await _seed_order(db_session)
    first = await payme_svc.create_transaction(
        db_session,
        payme_id="pt-replay",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    second = await payme_svc.create_transaction(
        db_session,
        payme_id="pt-replay",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    assert first == second
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(PaymeTransaction)
            .where(PaymeTransaction.payme_id == "pt-replay")
        )
    ).scalar_one()
    assert count == 1


async def test_create_transaction_wrong_amount_is_31001(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    with pytest.raises(PaymeError) as exc:
        await payme_svc.create_transaction(
            db_session,
            payme_id="pt-badamount",
            time=1_700_000_000_000,
            amount=EXPECTED_TIYIN - 5,
            account={"order_id": order_id},
        )
    assert exc.value.code == -31001


async def test_create_second_active_tx_same_order_is_31099(
    db_session: AsyncSession,
) -> None:
    order_id = await _seed_order(db_session)
    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-active-a",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    with pytest.raises(PaymeError) as exc:
        await payme_svc.create_transaction(
            db_session,
            payme_id="pt-active-b",
            time=1_700_000_000_001,
            amount=EXPECTED_TIYIN,
            account={"order_id": order_id},
        )
    # Payme mandates an account-range error (-31050..-31099) for a busy order,
    # not the generic -31008 — the sandbox's "new transaction" case asserts this.
    assert -31099 <= exc.value.code <= -31050


async def test_create_transaction_reuses_pending_payme_payment(
    db_session: AsyncSession,
) -> None:
    order_id = await _seed_order(db_session)
    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="payme",
            status="pending",
            amount=Decimal("130000.00"),
            currency="UZS",
            external_id=f"payme:{order_id}",
        )
    )
    await db_session.flush()

    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-reuse",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    row = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-reuse")
        )
    ).scalar_one()
    # Reused the pre-existing pending payment rather than creating a second one.
    assert row.payment_id == payment_id
    count = (
        await db_session.execute(
            select(func.count()).select_from(Payment).where(Payment.order_id == order_id)
        )
    ).scalar_one()
    assert count == 1


async def test_create_replay_with_different_amount_is_31001(
    db_session: AsyncSession,
) -> None:
    order_id = await _seed_order(db_session)
    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-replay-badamt",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    with pytest.raises(PaymeError) as exc:
        await payme_svc.create_transaction(
            db_session,
            payme_id="pt-replay-badamt",
            time=1_700_000_000_000,
            amount=EXPECTED_TIYIN + 7,
            account={"order_id": order_id},
        )
    assert exc.value.code == -31001


async def test_check_perform_non_integral_charge_is_31001(
    db_session: AsyncSession,
) -> None:
    # A sub-tiyin charge cannot be expressed as an integer amount — corrupt
    # order data is surfaced as -31001, never silently truncated.
    order_id = await _seed_order(db_session, total_charged=Decimal("130000.005"))
    with pytest.raises(PaymeError) as exc:
        await payme_svc.check_perform_transaction(
            db_session, amount=13_000_000, account={"order_id": order_id}
        )
    assert exc.value.code == -31001


# ---------- perform_transaction ----------


async def test_perform_transaction_walks_to_state_2_and_pays(
    db_session: AsyncSession,
) -> None:
    order_id = await _seed_order(db_session)
    created = await payme_svc.create_transaction(
        db_session,
        payme_id="pt-perform",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    result = await payme_svc.perform_transaction(db_session, payme_id="pt-perform")
    assert result["state"] == 2
    assert result["perform_time"] > 0
    assert result["transaction"] == created["transaction"]

    row = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-perform")
        )
    ).scalar_one()
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    # settle walked the order off ``pending_payment`` (through the single paid
    # chokepoint) and kicked the fulfilment saga; the exact resting status
    # depends on the saga, but it is no longer pending.
    assert order.status != "pending_payment"
    assert order.paid_at is not None


async def test_perform_transaction_replay_is_idempotent(
    db_session: AsyncSession,
) -> None:
    order_id = await _seed_order(db_session)
    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-perform-replay",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    first = await payme_svc.perform_transaction(db_session, payme_id="pt-perform-replay")
    second = await payme_svc.perform_transaction(db_session, payme_id="pt-perform-replay")
    assert first == second


async def test_perform_unknown_is_31003(db_session: AsyncSession) -> None:
    with pytest.raises(PaymeError) as exc:
        await payme_svc.perform_transaction(db_session, payme_id="nope")
    assert exc.value.code == -31003


async def test_perform_on_cancelled_is_31008(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-perform-cancelled",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    await payme_svc.cancel_transaction(db_session, payme_id="pt-perform-cancelled", reason=1)
    with pytest.raises(PaymeError) as exc:
        await payme_svc.perform_transaction(db_session, payme_id="pt-perform-cancelled")
    assert exc.value.code == -31008


# ---------- cancel_transaction ----------


async def test_cancel_state_1_goes_to_minus_1(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-cancel-1",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    result = await payme_svc.cancel_transaction(db_session, payme_id="pt-cancel-1", reason=1)
    assert result["state"] == -1
    assert result["cancel_time"] > 0

    row = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-cancel-1")
        )
    ).scalar_one()
    assert row.reason == 1
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == row.payment_id))
    ).scalar_one()
    assert payment.status == "cancelled"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "pending_payment"

    # Idempotent replay.
    replay = await payme_svc.cancel_transaction(db_session, payme_id="pt-cancel-1", reason=1)
    assert replay == result


async def test_cancel_state_2_refunds_to_minus_2(db_session: AsyncSession) -> None:
    # Seed an order that is PAID (not delivered) with a succeeded payme payment
    # and a performed transaction, so the state-2 cancel path takes the refund
    # branch rather than -31007.
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, status="paid")
    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="payme",
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
            external_id=f"payme:{order_id}",
        )
    )
    await db_session.flush()
    db_session.add(
        PaymeTransaction(
            id=str(uuid.uuid4()),
            payme_id="pt-cancel-2",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            state=2,
            create_time=1_700_000_000_000,
            perform_time=1_700_000_100_000,
        )
    )
    await db_session.flush()

    result = await payme_svc.cancel_transaction(db_session, payme_id="pt-cancel-2", reason=5)
    assert result["state"] == -2
    assert result["cancel_time"] > 0

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "refunded"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "refunded"


async def test_cancel_state_2_delivered_is_31007(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    order_id = await _make_order(db_session, user_id=user_id, status="delivered")
    payment_id = str(uuid.uuid4())
    db_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="payme",
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
        )
    )
    await db_session.flush()
    db_session.add(
        PaymeTransaction(
            id=str(uuid.uuid4()),
            payme_id="pt-cancel-delivered",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            state=2,
            create_time=1_700_000_000_000,
            perform_time=1_700_000_100_000,
        )
    )
    await db_session.flush()

    with pytest.raises(PaymeError) as exc:
        await payme_svc.cancel_transaction(db_session, payme_id="pt-cancel-delivered", reason=5)
    assert exc.value.code == -31007
    # Nothing was reversed.
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"


async def _seed_sku(db: AsyncSession) -> str:
    """Seed a minimal catalog and return a usable ``sku_id``."""
    category = Category(
        id=new_id(),
        slug="games-ps",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="steam-ps",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Steam")],
    )
    product = Product(
        id=new_id(),
        slug="steam-wallet-ps",
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
        sku_code="steam-ps-10",
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


async def test_cancel_state_2_partial_delivery_is_31007(
    db_session: AsyncSession,
) -> None:
    """A multi-item paid order where ONE item is already delivered (the other
    still in progress, so ``order.status == 'fulfilling'``) must refuse the
    state-2 auto-refund with -31007 — otherwise a full reverse would claw back
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

    # One task succeeded (goods shipped) + its Delivery row; one still open.
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
            provider="payme",
            status="succeeded",
            amount=Decimal("130000.00"),
            currency="UZS",
        )
    )
    await db_session.flush()
    db_session.add(
        PaymeTransaction(
            id=str(uuid.uuid4()),
            payme_id="pt-cancel-partial",
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            state=2,
            create_time=1_700_000_000_000,
            perform_time=1_700_000_100_000,
        )
    )
    await db_session.flush()

    with pytest.raises(PaymeError) as exc:
        await payme_svc.cancel_transaction(db_session, payme_id="pt-cancel-partial", reason=5)
    assert exc.value.code == -31007

    # No refund happened: the reverse hook was never reached.
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "succeeded"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "fulfilling"
    # The Payme transaction itself was NOT walked to -2.
    txn = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-cancel-partial")
        )
    ).scalar_one()
    assert txn.state == 2


async def test_cancel_unknown_is_31003(db_session: AsyncSession) -> None:
    with pytest.raises(PaymeError) as exc:
        await payme_svc.cancel_transaction(db_session, payme_id="nope", reason=1)
    assert exc.value.code == -31003


# ---------- check_transaction ----------


async def test_check_transaction_shape(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    created = await payme_svc.create_transaction(
        db_session,
        payme_id="pt-check",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    result = await payme_svc.check_transaction(db_session, payme_id="pt-check")
    assert result == {
        "create_time": 1_700_000_000_000,
        "perform_time": 0,
        "cancel_time": 0,
        "transaction": created["transaction"],
        "state": 1,
        "reason": None,
    }


async def test_check_transaction_unknown_is_31003(db_session: AsyncSession) -> None:
    with pytest.raises(PaymeError) as exc:
        await payme_svc.check_transaction(db_session, payme_id="nope")
    assert exc.value.code == -31003


# ---------- get_statement ----------


async def test_get_statement_window(db_session: AsyncSession) -> None:
    order_a = await _seed_order(db_session)
    order_b = await _seed_order(db_session)
    order_c = await _seed_order(db_session)
    # Three transactions at t=100, 200, 300.
    for payme_id, order_id, t in (
        ("pt-stmt-early", order_a, 100),
        ("pt-stmt-mid", order_b, 200),
        ("pt-stmt-late", order_c, 300),
    ):
        db_session.add(
            PaymeTransaction(
                id=str(uuid.uuid4()),
                payme_id=payme_id,
                order_id=order_id,
                amount_tiyin=EXPECTED_TIYIN,
                state=1,
                create_time=t,
            )
        )
    await db_session.flush()

    result = await payme_svc.get_statement(db_session, from_ms=150, to_ms=250)
    ids = [tx["id"] for tx in result["transactions"]]
    assert ids == ["pt-stmt-mid"]
    row = result["transactions"][0]
    assert row["time"] == 200
    assert row["amount"] == EXPECTED_TIYIN
    assert row["account"] == {"order_id": order_b}
    assert row["state"] == 1
    assert row["receivers"] == []


async def test_get_statement_orders_ascending(db_session: AsyncSession) -> None:
    order_a = await _seed_order(db_session)
    order_b = await _seed_order(db_session)
    db_session.add_all(
        [
            PaymeTransaction(
                id=str(uuid.uuid4()),
                payme_id="pt-asc-late",
                order_id=order_b,
                amount_tiyin=EXPECTED_TIYIN,
                state=1,
                create_time=500,
            ),
            PaymeTransaction(
                id=str(uuid.uuid4()),
                payme_id="pt-asc-early",
                order_id=order_a,
                amount_tiyin=EXPECTED_TIYIN,
                state=1,
                create_time=400,
            ),
        ]
    )
    await db_session.flush()
    result = await payme_svc.get_statement(db_session, from_ms=0, to_ms=1000)
    ids = [tx["id"] for tx in result["transactions"]]
    assert ids == ["pt-asc-early", "pt-asc-late"]


# ---------- set_fiscal_data ----------


async def test_set_fiscal_data_stores_by_type(db_session: AsyncSession) -> None:
    order_id = await _seed_order(db_session)
    await payme_svc.create_transaction(
        db_session,
        payme_id="pt-fiscal",
        time=1_700_000_000_000,
        amount=EXPECTED_TIYIN,
        account={"order_id": order_id},
    )
    result = await payme_svc.set_fiscal_data(
        db_session,
        payme_id="pt-fiscal",
        type_="PERFORM",
        fiscal_data={"receipt_id": 42, "status": "registered"},
    )
    assert result == {"success": True}
    row = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-fiscal")
        )
    ).scalar_one()
    assert row.fiscal_data == {"PERFORM": {"receipt_id": 42, "status": "registered"}}

    # A second type merges without clobbering the first.
    await payme_svc.set_fiscal_data(
        db_session,
        payme_id="pt-fiscal",
        type_="CANCEL",
        fiscal_data={"receipt_id": 43},
    )
    row = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.payme_id == "pt-fiscal")
        )
    ).scalar_one()
    assert set(row.fiscal_data) == {"PERFORM", "CANCEL"}


async def test_set_fiscal_data_unknown_is_32001(db_session: AsyncSession) -> None:
    with pytest.raises(PaymeError) as exc:
        await payme_svc.set_fiscal_data(
            db_session, payme_id="nope", type_="PERFORM", fiscal_data={}
        )
    assert exc.value.code == -32001


# ---------- build_checkout_url ----------


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        payme_merchant_id="MID123",
        payme_checkout_url="https://checkout.paycom.uz",
    )


async def test_build_checkout_url_no_return(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payme_svc, "get_settings", _fake_settings)
    url = payme_svc.build_checkout_url(order_id="ORDER-1", amount_tiyin=13_000_000, return_url=None)
    expected_payload = "m=MID123;ac.order_id=ORDER-1;a=13000000;l=ru"
    expected_b64 = base64.b64encode(expected_payload.encode()).decode()
    assert url == f"https://checkout.paycom.uz/{expected_b64}"


async def test_build_checkout_url_with_return_and_lang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(payme_svc, "get_settings", _fake_settings)
    url = payme_svc.build_checkout_url(
        order_id="ORDER-1",
        amount_tiyin=13_000_000,
        return_url="https://yupay.uz/return",
        lang="uz",
    )
    expected_payload = "m=MID123;ac.order_id=ORDER-1;a=13000000;c=https://yupay.uz/return;l=uz"
    expected_b64 = base64.b64encode(expected_payload.encode()).decode()
    assert url == f"https://checkout.paycom.uz/{expected_b64}"
