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
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User
from yupay.modules.uzum.models import UzumTransaction

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


async def _seed_confirmed_transaction(
    db: AsyncSession,
    *,
    trans_id: str,
    order_status: str,
    payment_status: str = "succeeded",
) -> str:
    """Seed an order + a succeeded ``uzum`` payment + a CONFIRMED transaction
    directly (bypassing ``/create`` + ``/confirm``), mirroring
    ``test_uzum_service.py``'s direct-seeding style for reverse-from-CONFIRMED
    scenarios. Returns the order id."""
    order_id = await _seed_order(db, status=order_status)
    payment_id = str(uuid.uuid4())
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="uzum",
            status=payment_status,
            amount=Decimal("130000.00"),
            currency="UZS",
        )
    )
    await db.flush()
    db.add(
        UzumTransaction(
            id=new_id(),
            trans_id=trans_id,
            order_id=order_id,
            payment_id=payment_id,
            amount_tiyin=EXPECTED_TIYIN,
            status="CONFIRMED",
            create_time=1_700_000_000_000,
            confirm_time=1_700_000_100_000,
        )
    )
    await db.commit()
    return order_id


def _install_flaky_commit(monkeypatch: pytest.MonkeyPatch, *, fail_calls: int = 1) -> None:
    """Make the next ``fail_calls`` ``AsyncSession.commit()`` calls raise, then
    delegate to the real implementation. Mirrors
    ``test_payme_merchant.py::test_commit_failure_is_32400_not_500`` — the
    route's own ``await db.commit()`` is the first call after this is
    installed (seeding already happened on a separate session), so it is the
    one that blows up; later commits (e.g. the ``get_session`` dependency's
    trailing commit) delegate to the real implementation."""
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    real_commit = _AsyncSession.commit
    calls = {"n": 0}

    async def _flaky_commit(self: _AsyncSession) -> None:
        calls["n"] += 1
        if calls["n"] <= fail_calls:
            raise RuntimeError("simulated commit failure")
        await real_commit(self)

    monkeypatch.setattr(_AsyncSession, "commit", _flaky_commit, raising=True)


def _install_flaky_rollback(monkeypatch: pytest.MonkeyPatch, *, fail_calls: int = 1) -> None:
    """Make the next ``fail_calls`` ``AsyncSession.rollback()`` calls raise,
    then delegate to the real implementation -- drives the
    ``_rollback_after_internal_error`` nested "rollback also fails" branch."""
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    real_rollback = _AsyncSession.rollback
    calls = {"n": 0}

    async def _flaky_rollback(self: _AsyncSession) -> None:
        calls["n"] += 1
        if calls["n"] <= fail_calls:
            raise RuntimeError("simulated rollback failure")
        await real_rollback(self)

    monkeypatch.setattr(_AsyncSession, "rollback", _flaky_rollback, raising=True)


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


@pytest.mark.parametrize("url", [CHECK_URL, CREATE_URL, CONFIRM_URL, REVERSE_URL, STATUS_URL])
async def test_non_post_get_is_10003(integration_client: AsyncClient, url: str) -> None:
    r = await integration_client.get(url)
    assert r.status_code == 200
    assert r.json() == {"status": "FAILED", "errorCode": 10003}


async def test_non_post_put_is_10003(integration_client: AsyncClient) -> None:
    r = await integration_client.put(CHECK_URL)
    assert r.status_code == 200
    assert r.json() == {"status": "FAILED", "errorCode": 10003}


async def test_valid_json_non_object_body_is_10002(integration_client: AsyncClient) -> None:
    """``_parse_body`` rejects valid JSON that isn't an object -- Uzum's
    envelope is always a JSON object, so a bare array/number/string is just as
    malformed as unparsable JSON."""
    r = await integration_client.post(
        CHECK_URL,
        headers={**_auth(), "content-type": "application/json"},
        content=b"[1, 2, 3]",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10002


@pytest.mark.parametrize("url", [CREATE_URL, CONFIRM_URL, REVERSE_URL, STATUS_URL])
async def test_malformed_json_on_other_endpoints_is_10002(
    integration_client: AsyncClient, url: str
) -> None:
    """The same ``_parse_body`` guard applies to every endpoint, not just
    ``/check`` -- each route has its own ``except UzumError: return
    exc.to_response()`` around the raw-body parse."""
    r = await integration_client.post(
        url,
        headers={**_auth(), "content-type": "application/json"},
        content=b"not json at all {",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10002


async def test_auth_malformed_base64_is_10001(integration_client: AsyncClient) -> None:
    """A Basic header whose payload isn't valid base64 at all (not merely a
    wrong login/password) must hit the decode-error branch, not the
    credential-mismatch one."""
    r = await integration_client.post(
        CHECK_URL,
        headers={"Authorization": "Basic not_base64_$$$"},
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": str(uuid.uuid4())}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10001


async def test_auth_decoded_credentials_missing_colon_is_10001(
    integration_client: AsyncClient,
) -> None:
    """Valid base64 that decodes to a string without a ``login:password``
    separator must also be rejected as 10001."""
    token = base64.b64encode(b"nocolonhere").decode()
    r = await integration_client.post(
        CHECK_URL,
        headers={"Authorization": f"Basic {token}"},
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": str(uuid.uuid4())}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10001


async def test_check_missing_order_id_key_is_10005(integration_client: AsyncClient) -> None:
    """``params`` present but empty -- ``_req_str`` must reject the missing
    ``order_id`` key with 10005 (distinct from an unknown-but-present
    ``order_id``, which is the service-level 10007)."""
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10005


async def test_check_params_not_object_is_10005(integration_client: AsyncClient) -> None:
    """``params`` present but not a JSON object -- ``_req_dict`` must reject it
    with 10005."""
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": "not-an-object"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10005


async def test_confirm_missing_trans_id_is_10005(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        CONFIRM_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10005


async def test_reverse_missing_trans_id_is_10005(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10005


async def test_status_missing_trans_id_is_10005(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10005


# --------------------------------------------------------------------------- #
# Internal-error path: a commit-time (or rollback-time) infra failure must    #
# render as 99999 at HTTP 200, never escape as a 500 -- mirrors               #
# test_payme_merchant.py::test_commit_failure_is_32400_not_500.               #
# --------------------------------------------------------------------------- #


async def test_check_internal_error_and_rollback_failure_is_99999(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both the commit AND the best-effort rollback fail -- drives
    ``_rollback_after_internal_error``'s nested "rollback also fails" branch
    (it must still log and return 99999, never raise)."""
    order_id = await _seed_order(db_session)
    _install_flaky_commit(monkeypatch)
    _install_flaky_rollback(monkeypatch)

    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "params": {"order_id": order_id}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 99999
    assert body["serviceId"] == SERVICE_ID


async def test_create_internal_error_is_99999(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = await _seed_order(db_session)
    _install_flaky_commit(monkeypatch)

    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": str(uuid.uuid4()),
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 99999


async def test_confirm_internal_error_is_99999(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.json()["status"] == "CREATED"

    _install_flaky_commit(monkeypatch)
    r = await integration_client.post(
        CONFIRM_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 99999


async def test_reverse_internal_error_is_99999(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.json()["status"] == "CREATED"

    _install_flaky_commit(monkeypatch)
    r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 99999


async def test_status_internal_error_is_99999(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.json()["status"] == "CREATED"

    _install_flaky_commit(monkeypatch)
    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 99999


# --------------------------------------------------------------------------- #
# /create service-level error codes, driven through the route                 #
# --------------------------------------------------------------------------- #


async def test_create_wrong_amount_is_10011(
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
            "amount": EXPECTED_TIYIN - 5,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10011
    assert body["serviceId"] == SERVICE_ID


async def test_create_already_paid_order_is_10008(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session, status="paid")
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": str(uuid.uuid4()),
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10008


async def test_create_cancelled_order_is_10009(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session, status="cancelled")
    r = await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": str(uuid.uuid4()),
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10009


async def test_create_duplicate_trans_id_is_10010(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    create_req = {
        "serviceId": SERVICE_ID,
        "timestamp": 1,
        "transId": trans_id,
        "params": {"order_id": order_id},
        "amount": EXPECTED_TIYIN,
    }
    first = await integration_client.post(CREATE_URL, headers=_auth(), json=create_req)
    assert first.json()["status"] == "CREATED"

    second = await integration_client.post(CREATE_URL, headers=_auth(), json=create_req)
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10010
    assert body["transId"] == trans_id


# --------------------------------------------------------------------------- #
# /confirm service-level error codes, driven through the route                #
# --------------------------------------------------------------------------- #


async def test_confirm_unknown_trans_id_is_10014(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        CONFIRM_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "transId": "nope"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10014
    assert body["transId"] == "nope"


async def test_confirm_already_confirmed_is_10016(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    confirm_req = {"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id}
    first = await integration_client.post(CONFIRM_URL, headers=_auth(), json=confirm_req)
    assert first.json()["status"] == "CONFIRMED"

    second = await integration_client.post(CONFIRM_URL, headers=_auth(), json=confirm_req)
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10016
    assert body["transId"] == trans_id


async def test_confirm_on_reversed_is_10015(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    reverse_r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
    )
    assert reverse_r.json()["status"] == "REVERSED"

    r = await integration_client.post(
        CONFIRM_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 3, "transId": trans_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10015
    assert body["transId"] == trans_id


# --------------------------------------------------------------------------- #
# /reverse service-level error codes, driven through the route                #
# --------------------------------------------------------------------------- #


async def test_reverse_unknown_trans_id_is_10014(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "transId": "nope"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10014
    assert body["transId"] == "nope"


async def test_reverse_already_reversed_is_10018(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    await integration_client.post(
        CREATE_URL,
        headers=_auth(),
        json={
            "serviceId": SERVICE_ID,
            "timestamp": 1,
            "transId": trans_id,
            "params": {"order_id": order_id},
            "amount": EXPECTED_TIYIN,
        },
    )
    reverse_req = {"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id}
    first = await integration_client.post(REVERSE_URL, headers=_auth(), json=reverse_req)
    assert first.json()["status"] == "REVERSED"

    second = await integration_client.post(REVERSE_URL, headers=_auth(), json=reverse_req)
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10018
    assert body["transId"] == trans_id


async def test_reverse_confirmed_delivered_order_is_10017(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    trans_id = f"uz-http-delivered-{uuid.uuid4()}"
    await _seed_confirmed_transaction(db_session, trans_id=trans_id, order_status="delivered")

    r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "transId": trans_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10017
    assert body["transId"] == trans_id

    # Nothing was reversed.
    txn = (
        await db_session.execute(
            select(UzumTransaction).where(UzumTransaction.trans_id == trans_id)
        )
    ).scalar_one()
    assert txn.status == "CONFIRMED"


async def test_reverse_confirmed_not_delivered_reverses_ledger(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A CONFIRMED transaction on a paid-but-not-delivered order reverses the
    ledger via HTTP -- the route's success path for the CONFIRMED branch."""
    trans_id = f"uz-http-confirmed-{uuid.uuid4()}"
    order_id = await _seed_confirmed_transaction(db_session, trans_id=trans_id, order_status="paid")

    r = await integration_client.post(
        REVERSE_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "transId": trans_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "REVERSED"
    assert body["transId"] == trans_id

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "refunded"
    payment = (
        await db_session.execute(
            select(Payment).where(Payment.order_id == order_id, Payment.provider == "uzum")
        )
    ).scalar_one()
    assert payment.status == "refunded"


# --------------------------------------------------------------------------- #
# /status, driven through the route                                          #
# --------------------------------------------------------------------------- #


async def test_status_unknown_trans_id_is_10014(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 1, "transId": "nope"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["errorCode"] == 10014
    assert body["transId"] == "nope"


async def test_status_full_envelope_created(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    created = (
        await integration_client.post(
            CREATE_URL,
            headers=_auth(),
            json={
                "serviceId": SERVICE_ID,
                "timestamp": 1,
                "transId": trans_id,
                "params": {"order_id": order_id},
                "amount": EXPECTED_TIYIN,
            },
        )
    ).json()

    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
    )
    assert r.status_code == 200
    assert r.json() == {
        "serviceId": SERVICE_ID,
        "transId": trans_id,
        "status": "CREATED",
        "transTime": created["transTime"],
        "confirmTime": None,
        "reverseTime": None,
        "data": {},
        "amount": EXPECTED_TIYIN,
    }


async def test_status_full_envelope_confirmed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    created = (
        await integration_client.post(
            CREATE_URL,
            headers=_auth(),
            json={
                "serviceId": SERVICE_ID,
                "timestamp": 1,
                "transId": trans_id,
                "params": {"order_id": order_id},
                "amount": EXPECTED_TIYIN,
            },
        )
    ).json()
    confirmed = (
        await integration_client.post(
            CONFIRM_URL,
            headers=_auth(),
            json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
        )
    ).json()

    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 3, "transId": trans_id},
    )
    assert r.status_code == 200
    assert r.json() == {
        "serviceId": SERVICE_ID,
        "transId": trans_id,
        "status": "CONFIRMED",
        "transTime": created["transTime"],
        "confirmTime": confirmed["confirmTime"],
        "reverseTime": None,
        "data": {},
        "amount": EXPECTED_TIYIN,
    }


async def test_status_full_envelope_reversed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    trans_id = str(uuid.uuid4())
    created = (
        await integration_client.post(
            CREATE_URL,
            headers=_auth(),
            json={
                "serviceId": SERVICE_ID,
                "timestamp": 1,
                "transId": trans_id,
                "params": {"order_id": order_id},
                "amount": EXPECTED_TIYIN,
            },
        )
    ).json()
    reversed_body = (
        await integration_client.post(
            REVERSE_URL,
            headers=_auth(),
            json={"serviceId": SERVICE_ID, "timestamp": 2, "transId": trans_id},
        )
    ).json()

    r = await integration_client.post(
        STATUS_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": 3, "transId": trans_id},
    )
    assert r.status_code == 200
    assert r.json() == {
        "serviceId": SERVICE_ID,
        "transId": trans_id,
        "status": "REVERSED",
        "transTime": created["transTime"],
        "confirmTime": None,
        "reverseTime": reversed_body["reverseTime"],
        "data": {},
        "amount": EXPECTED_TIYIN,
    }


# --------------------------------------------------------------------------- #
# /check response envelope: amount in data + response-time timestamp          #
# --------------------------------------------------------------------------- #


async def test_check_returns_amount_and_response_timestamp(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """``/check`` echoes ``serviceId`` but returns its OWN response-time
    ``timestamp`` (never the request's), and carries the order's charge in
    ``data.amount.value`` (sums) so Uzum's app prefills the amount."""
    order_id = await _seed_order(db_session)  # total_charged 130000.00
    request_ts = 1_700_000_000_000  # a fixed past timestamp (2023-11-14)
    r = await integration_client.post(
        CHECK_URL,
        headers=_auth(),
        json={"serviceId": SERVICE_ID, "timestamp": request_ts, "params": {"order_id": order_id}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK"
    assert body["serviceId"] == SERVICE_ID
    assert body["data"] == {"amount": {"value": "130000"}}
    # timestamp is our response time, NOT the echoed request value.
    assert body["timestamp"] != request_ts
    assert body["timestamp"] > request_ts


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
    assert r.json()["data"] == {"amount": {"value": "130000"}}

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
