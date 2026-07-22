"""End-to-end tests for the Uzum Bank Merchant API REST webhooks.

These drive the mounted FastAPI app over HTTP exactly as Uzum's sandbox does:
five ``POST /api/v1/payments/uzum/{check,create,confirm,reverse,status}``
routes, each carrying HTTP Basic auth and a JSON body. This is the REST twin
of ``test_payme_merchant.py`` — the transport contract is the same "always
HTTP 200, failures carry an error code in the body" rule Payme uses, just
with Uzum's own envelope (``serviceId``/``transId``/``status``/``errorCode``)
instead of JSON-RPC.

Every response, success or failure, is HTTP 200.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

CHECK_URL = "/api/v1/payments/uzum/check"
CREATE_URL = "/api/v1/payments/uzum/create"
CONFIRM_URL = "/api/v1/payments/uzum/confirm"
REVERSE_URL = "/api/v1/payments/uzum/reverse"
STATUS_URL = "/api/v1/payments/uzum/status"

SERVICE_ID = 101202
UZUM_LOGIN = "uzum-merchant"
UZUM_PASSWORD = "prod-secret"
TEST_LOGIN = "uzum-sandbox"
TEST_PASSWORD = "sandbox-secret"
# 130000.00 UZS * 100 = 13_000_000 tiyin
EXPECTED_TIYIN = 13_000_000


@pytest.fixture(autouse=True)
def _uzum_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UZUM_SERVICE_ID", str(SERVICE_ID))
    monkeypatch.setenv("UZUM_LOGIN", UZUM_LOGIN)
    monkeypatch.setenv("UZUM_PASSWORD", UZUM_PASSWORD)
    monkeypatch.setenv("UZUM_TEST_LOGIN", TEST_LOGIN)
    monkeypatch.setenv("UZUM_TEST_PASSWORD", TEST_PASSWORD)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _auth(login: str = TEST_LOGIN, password: str = TEST_PASSWORD) -> dict[str, str]:
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _seed_order(
    db: AsyncSession,
    *,
    status: str = "pending_payment",
    total_charged: Decimal = Decimal("130000.00"),
) -> str:
    user_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
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
    await db.commit()
    return order_id


# --------------------------------------------------------------------------- #
# Transport-level failures                                                    #
# --------------------------------------------------------------------------- #


async def test_missing_auth_is_10001(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        CHECK_URL,
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": str(uuid.uuid4())}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10001


async def test_invalid_auth_is_10001(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(password="wrong-password"),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": str(uuid.uuid4())}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10001


async def test_unknown_order_on_check_is_10007(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": str(uuid.uuid4())}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10007


async def test_wrong_service_id_is_10006(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID + 1, "timestamp": 1, "params": {"order_id": order_id}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10006


async def test_malformed_json_is_10002(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        CHECK_URL,
        headers={**_auth(), "content-type": "application/json"},
        content=b"not json at all {",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10002


async def test_missing_amount_on_create_is_10005(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": str(uuid.uuid4()),
            "params": {"order_id": order_id},
            # "amount" deliberately omitted.
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10005


# --------------------------------------------------------------------------- #
# Happy path across all five endpoints                                        #
# --------------------------------------------------------------------------- #


async def test_happy_path_check_create_confirm_status(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())

    # /check -> OK
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": order_id}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "OK"
    assert r.json()["serviceId"] == SERVICE_ID

    # /create -> CREATED
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1_700_000_000_000,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.status_code == 200
    created = r.json()
    assert created["status"] == "CREATED"
    assert created["transId"] == trans_id
    assert created["amount"] == EXPECTED_TIYIN

    # /confirm -> CONFIRMED; order becomes paid.
    r = await integration_client.post(
        CONFIRM_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1_700_000_001_000,
            "transId": trans_id,
            "paymentSource": "INSTALLMENT",
            "tariff": "003",
            "processingReferenceNumber": "000",
            "phone": "998901234567",
            "cardType": 2,
        },
    )
    assert r.status_code == 200
    confirmed = r.json()
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["transId"] == trans_id

    # The order leaves pending_payment as soon as /confirm settles the
    # payment; it may progress further (fulfilling/delivered) synchronously
    # via the in-process fulfilment saga, same as the Payme merchant test.
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status != "pending_payment"
    assert order.paid_at is not None
    payment = (
        await db_session.execute(
            select(Payment).where(Payment.order_id == order_id, Payment.provider == "uzum")
        )
    ).scalar_one()
    assert payment.status == "succeeded"

    # /status -> CONFIRMED
    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1_700_000_002_000, "transId": trans_id},
    )
    assert r.status_code == 200
    status_body = r.json()
    assert status_body["status"] == "CONFIRMED"
    assert status_body["transId"] == trans_id


async def test_reverse_fresh_non_delivered_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())

    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1_700_000_000_000,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "CREATED"

    # /reverse on a CREATED (not yet confirmed) transaction -> REVERSED.
    r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1_700_000_001_000, "transId": trans_id},
    )
    assert r.status_code == 200
    reversed_body = r.json()
    assert reversed_body["status"] == "REVERSED"
    assert reversed_body["transId"] == trans_id

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "pending_payment"
