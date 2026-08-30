"""End-to-end tests for the Click Shop API webhooks.

These drive the mounted FastAPI app over HTTP exactly as Click's servers do:
two ``POST /api/v1/payments/click/{prepare,complete}`` routes, each carrying
an ``application/x-www-form-urlencoded`` body MD5-signed via ``sign_string``.
This is the form-encoded twin of ``test_uzum_webhook.py`` -- the transport
contract is the same "always HTTP 200, failures carry an error code in the
body" rule Uzum/Payme use, just with Click's own envelope (``error``/
``error_note``/``merchant_prepare_id``) instead of ``status``/``errorCode``.

Every response, success or failure, is HTTP 200.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.click.models import ClickTransaction
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

PREPARE_URL = "/api/v1/payments/click/prepare"
COMPLETE_URL = "/api/v1/payments/click/complete"

SERVICE_ID = 108149
BOT_SERVICE_ID = 108150
SECRET = "web-secret-abc"
BOT_SECRET = "bot-secret-xyz"

TOTAL_CHARGED = Decimal("130000.00")
AMOUNT_STR = str(TOTAL_CHARGED)


@pytest.fixture(autouse=True)
def _click_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", str(SERVICE_ID))
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", str(BOT_SERVICE_ID))
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", SECRET)
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", BOT_SECRET)
    monkeypatch.setenv("CLICK_MERCHANT_ID", "63276")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _md5(*parts: str) -> str:
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _prepare_sign(
    *,
    click_trans_id: str,
    service_id: str = str(SERVICE_ID),
    secret: str = SECRET,
    merchant_trans_id: str,
    amount: str,
    action: str = "0",
    sign_time: str = "2026-07-23 10:00:00",
) -> str:
    return _md5(click_trans_id, service_id, secret, merchant_trans_id, amount, action, sign_time)


def _complete_sign(
    *,
    click_trans_id: str,
    service_id: str = str(SERVICE_ID),
    secret: str = SECRET,
    merchant_trans_id: str,
    merchant_prepare_id: str,
    amount: str,
    action: str = "1",
    sign_time: str = "2026-07-23 10:05:00",
) -> str:
    return _md5(
        click_trans_id,
        service_id,
        secret,
        merchant_trans_id,
        merchant_prepare_id,
        amount,
        action,
        sign_time,
    )


def _prepare_body(
    *,
    click_trans_id: str,
    merchant_trans_id: str,
    amount: str = AMOUNT_STR,
    action: str = "0",
    error: str = "0",
    service_id: str = str(SERVICE_ID),
    secret: str = SECRET,
    sign_time: str = "2026-07-23 10:00:00",
    sign_string: str | None = None,
    click_paydoc_id: str = "5001",
) -> dict[str, str]:
    sign = sign_string or _prepare_sign(
        click_trans_id=click_trans_id,
        service_id=service_id,
        secret=secret,
        merchant_trans_id=merchant_trans_id,
        amount=amount,
        action=action,
        sign_time=sign_time,
    )
    return {
        "click_trans_id": click_trans_id,
        "service_id": service_id,
        "click_paydoc_id": click_paydoc_id,
        "merchant_trans_id": merchant_trans_id,
        "amount": amount,
        "action": action,
        "error": error,
        "error_note": "Success" if error == "0" else "cancelled",
        "sign_time": sign_time,
        "sign_string": sign,
    }


def _complete_body(
    *,
    click_trans_id: str,
    merchant_trans_id: str,
    merchant_prepare_id: str,
    amount: str = AMOUNT_STR,
    action: str = "1",
    error: str = "0",
    service_id: str = str(SERVICE_ID),
    secret: str = SECRET,
    sign_time: str = "2026-07-23 10:05:00",
    sign_string: str | None = None,
    click_paydoc_id: str = "5001",
) -> dict[str, str]:
    sign = sign_string or _complete_sign(
        click_trans_id=click_trans_id,
        service_id=service_id,
        secret=secret,
        merchant_trans_id=merchant_trans_id,
        merchant_prepare_id=merchant_prepare_id,
        amount=amount,
        action=action,
        sign_time=sign_time,
    )
    return {
        "click_trans_id": click_trans_id,
        "service_id": service_id,
        "click_paydoc_id": click_paydoc_id,
        "merchant_trans_id": merchant_trans_id,
        "merchant_prepare_id": merchant_prepare_id,
        "amount": amount,
        "action": action,
        "error": error,
        "error_note": "Success" if error == "0" else "cancelled",
        "sign_time": sign_time,
        "sign_string": sign,
    }


async def _seed_order(
    db: AsyncSession,
    *,
    status: str = "pending_payment",
    total_charged: Decimal = TOTAL_CHARGED,
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


async def _seed_guest_order_with_evidence(
    db: AsyncSession,
    *,
    ip_country: str,
    total_charged: Decimal = TOTAL_CHARGED,
) -> str:
    """A guest catalog order plus the ``order_evidence`` row the pre-charge
    veto (ADR-0063) reads ``ip_country`` from."""
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=None,
            guest_email=f"guest-{order_id[:8]}@example.com",
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=total_charged,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db.flush()
    db.add(
        OrderEvidence(
            order_id=order_id,
            ip_country=ip_country,
            purge_after=datetime.now(UTC) + timedelta(days=90),
        )
    )
    await db.commit()
    return order_id


def _install_flaky_commit(monkeypatch: pytest.MonkeyPatch, *, fail_calls: int = 1) -> None:
    """Make the next ``fail_calls`` ``AsyncSession.commit()`` calls raise, then
    delegate to the real implementation. Mirrors
    ``test_uzum_webhook.py::_install_flaky_commit`` -- the route's own
    ``await db.commit()`` is the first call after this is installed (seeding
    already happened on a separate session), so it is the one that blows up."""
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
# Happy path: /prepare then /complete                                        #
# --------------------------------------------------------------------------- #


async def test_prepare_then_complete_happy_path(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    click_trans_id = "9001"

    r = await integration_client.post(
        PREPARE_URL,
        data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
    )
    assert r.status_code == 200
    prepared = r.json()
    assert prepared["error"] == 0
    assert prepared["error_note"] == "Success"
    assert prepared["click_trans_id"] == int(click_trans_id)
    assert prepared["merchant_trans_id"] == order_id
    assert isinstance(prepared["merchant_prepare_id"], int)

    merchant_prepare_id = str(prepared["merchant_prepare_id"])

    r = await integration_client.post(
        COMPLETE_URL,
        data=_complete_body(
            click_trans_id=click_trans_id,
            merchant_trans_id=order_id,
            merchant_prepare_id=merchant_prepare_id,
        ),
    )
    assert r.status_code == 200
    completed = r.json()
    assert completed["error"] == 0
    assert completed["error_note"] == "Success"
    assert completed["merchant_confirm_id"] == prepared["merchant_prepare_id"]

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status != "pending_payment"
    assert order.paid_at is not None

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.order_id == order_id, Payment.provider == "click")
        )
    ).scalar_one()
    assert payment.status == "succeeded"


# --------------------------------------------------------------------------- #
# Signature guard                                                             #
# --------------------------------------------------------------------------- #


async def test_prepare_tampered_sign_string_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    body = _prepare_body(click_trans_id="9002", merchant_trans_id=order_id)
    body["sign_string"] = "0" * 32 if body["sign_string"] != "0" * 32 else "1" * 32

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -1
    assert resp["error_note"] == "SIGN CHECK FAILED!"


async def test_prepare_unknown_service_id_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    body = _prepare_body(
        click_trans_id="9003",
        merchant_trans_id=order_id,
        service_id="999999",
        secret="whatever",
    )

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -1
    assert resp["error_note"] == "SIGN CHECK FAILED!"


async def test_complete_tampered_sign_string_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    click_trans_id = "9020"
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
    ).json()

    body = _complete_body(
        click_trans_id=click_trans_id,
        merchant_trans_id=order_id,
        merchant_prepare_id=str(prepared["merchant_prepare_id"]),
    )
    body["sign_string"] = "0" * 32 if body["sign_string"] != "0" * 32 else "1" * 32

    r = await integration_client.post(COMPLETE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -1
    assert resp["error_note"] == "SIGN CHECK FAILED!"


async def test_complete_unknown_service_id_is_minus1(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    click_trans_id = "9021"
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
    ).json()

    body = _complete_body(
        click_trans_id=click_trans_id,
        merchant_trans_id=order_id,
        merchant_prepare_id=str(prepared["merchant_prepare_id"]),
        service_id="999999",
        secret="whatever",
    )

    r = await integration_client.post(COMPLETE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -1
    assert resp["error_note"] == "SIGN CHECK FAILED!"


async def test_complete_service_error_is_echoed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A wrong ``amount``, correctly signed for itself, passes the route's
    signature guard but fails ``service.complete()``'s amount check against
    the amount recorded at Prepare time -- the route's ``except ClickError``
    handler (routes.py:274-275) must render the resulting ``-2`` at HTTP 200,
    never let it escape uncaught."""
    order_id = await _seed_order(db_session)
    click_trans_id = "9022"
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
    ).json()

    wrong_amount = str(TOTAL_CHARGED - Decimal("1.00"))
    body = _complete_body(
        click_trans_id=click_trans_id,
        merchant_trans_id=order_id,
        merchant_prepare_id=str(prepared["merchant_prepare_id"]),
        amount=wrong_amount,
    )

    r = await integration_client.post(COMPLETE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -2
    assert resp["error_note"] == "Incorrect parameter amount"


# --------------------------------------------------------------------------- #
# action guard                                                                #
# --------------------------------------------------------------------------- #


async def test_prepare_wrong_action_is_minus3(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    body = _prepare_body(click_trans_id="9004", merchant_trans_id=order_id, action="5")

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -3
    assert resp["error_note"] == "Action not found"


async def test_complete_wrong_action_is_minus3(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id="9005", merchant_trans_id=order_id),
        )
    ).json()

    body = _complete_body(
        click_trans_id="9005",
        merchant_trans_id=order_id,
        merchant_prepare_id=str(prepared["merchant_prepare_id"]),
        action="5",
    )
    r = await integration_client.post(COMPLETE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -3
    assert resp["error_note"] == "Action not found"


# --------------------------------------------------------------------------- #
# Amount / unknown order                                                     #
# --------------------------------------------------------------------------- #


async def test_prepare_wrong_amount_is_minus2(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session, total_charged=TOTAL_CHARGED)
    wrong_amount = str(TOTAL_CHARGED - Decimal("1.00"))
    body = _prepare_body(click_trans_id="9006", merchant_trans_id=order_id, amount=wrong_amount)

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -2
    assert resp["error_note"] == "Incorrect parameter amount"


async def test_prepare_unknown_order_is_minus5(integration_client: AsyncClient) -> None:
    body = _prepare_body(click_trans_id="9007", merchant_trans_id=str(uuid.uuid4()))

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -5
    assert resp["error_note"] == "User does not exist"


# --------------------------------------------------------------------------- #
# Negative inbound error -> cancel + -9                                      #
# --------------------------------------------------------------------------- #


async def test_prepare_negative_inbound_error_cancels_and_returns_minus9(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    click_trans_id = "9008"

    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
    ).json()
    assert prepared["error"] == 0

    body = _prepare_body(
        click_trans_id=click_trans_id,
        merchant_trans_id=order_id,
        error="-5000",
    )
    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -9
    assert resp["error_note"] == "Transaction cancelled"

    txn = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == int(click_trans_id))
        )
    ).scalar_one()
    assert txn.status == "CANCELLED"

    payment = (
        await db_session.execute(select(Payment).where(Payment.id == txn.payment_id))
    ).scalar_one()
    assert payment.status == "cancelled"


async def test_complete_negative_inbound_error_cancels_and_returns_minus9(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    click_trans_id = "9009"

    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
    ).json()
    merchant_prepare_id = str(prepared["merchant_prepare_id"])

    body = _complete_body(
        click_trans_id=click_trans_id,
        merchant_trans_id=order_id,
        merchant_prepare_id=merchant_prepare_id,
        error="-5000",
    )
    r = await integration_client.post(COMPLETE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -9
    assert resp["error_note"] == "Transaction cancelled"

    txn = (
        await db_session.execute(
            select(ClickTransaction).where(
                ClickTransaction.merchant_prepare_id == int(merchant_prepare_id)
            )
        )
    ).scalar_one()
    assert txn.status == "CANCELLED"


# --------------------------------------------------------------------------- #
# Internal-error path: a commit-time (or rollback-time) infra failure must    #
# render as -7 at HTTP 200, never escape as a 500 -- mirrors                  #
# test_uzum_webhook.py::test_check_internal_error_and_rollback_failure_is_99999#
# --------------------------------------------------------------------------- #


async def test_prepare_commit_failure_is_minus7(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id = await _seed_order(db_session)
    _install_flaky_commit(monkeypatch)

    r = await integration_client.post(
        PREPARE_URL,
        data=_prepare_body(click_trans_id="9012", merchant_trans_id=order_id),
    )
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -7
    assert resp["error_note"] == "Failed to update user"


async def test_prepare_commit_and_rollback_both_fail_is_minus7(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both the commit AND the best-effort rollback fail -- drives
    ``_rollback_after_internal_error``'s nested "rollback also fails" branch
    (it must still log and return -7, never raise)."""
    order_id = await _seed_order(db_session)
    _install_flaky_commit(monkeypatch)
    _install_flaky_rollback(monkeypatch)

    r = await integration_client.post(
        PREPARE_URL,
        data=_prepare_body(click_trans_id="9013", merchant_trans_id=order_id),
    )
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -7
    assert resp["error_note"] == "Failed to update user"


async def test_complete_commit_failure_is_minus7(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id = await _seed_order(db_session)
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id="9014", merchant_trans_id=order_id),
        )
    ).json()

    _install_flaky_commit(monkeypatch)
    r = await integration_client.post(
        COMPLETE_URL,
        data=_complete_body(
            click_trans_id="9014",
            merchant_trans_id=order_id,
            merchant_prepare_id=str(prepared["merchant_prepare_id"]),
        ),
    )
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -7
    assert resp["error_note"] == "Failed to update user"


# --------------------------------------------------------------------------- #
# Missing required field                                                     #
# --------------------------------------------------------------------------- #


async def test_prepare_missing_field_is_minus8(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    body = _prepare_body(click_trans_id="9010", merchant_trans_id=order_id)
    del body["sign_time"]

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -8
    assert resp["error_note"] == "Error in request from click"


async def test_prepare_non_numeric_click_trans_id_is_minus8(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A field that IS present but isn't a valid integer literal (``_req_int``'s
    ``ValueError`` branch) is just as malformed as a missing field."""
    order_id = await _seed_order(db_session)
    body = _prepare_body(click_trans_id="not-a-number", merchant_trans_id=order_id)
    # The sign_string would never match Click's real formula for a non-numeric
    # click_trans_id anyway, but the malformed-field guard fires first (it's
    # inside the same guard `try` ahead of the signature check).

    r = await integration_client.post(PREPARE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -8
    assert resp["error_note"] == "Error in request from click"


async def test_complete_missing_merchant_prepare_id_is_minus8(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id="9011", merchant_trans_id=order_id),
        )
    ).json()

    body = _complete_body(
        click_trans_id="9011",
        merchant_trans_id=order_id,
        merchant_prepare_id=str(prepared["merchant_prepare_id"]),
    )
    del body["merchant_prepare_id"]

    r = await integration_client.post(COMPLETE_URL, data=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["error"] == -8
    assert resp["error_note"] == "Error in request from click"


# --------------------------------------------------------------------------- #
# Malformed body (never a 500, even before signature verification runs)      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [PREPARE_URL, COMPLETE_URL])
async def test_malformed_multipart_body_is_minus8(
    integration_client: AsyncClient, url: str
) -> None:
    """A malformed ``multipart/form-data`` body must never escape
    ``request.form()`` as an uncaught ``MultipartParseError`` -- Click has no
    IP allowlist (the signature is the gate), so any unauthenticated request
    with an unparseable body must fail closed to ``-8`` at HTTP 200 BEFORE
    signature verification even runs. Regression test for the critical
    form-parse-escapes-the-always-HTTP-200-contract fix; fails with a 500
    pre-fix."""
    r = await integration_client.post(
        url,
        headers={"content-type": "multipart/form-data; boundary=X"},
        content=b"not a valid multipart body at all",
    )
    assert r.status_code == 200
    assert r.json() == {"error": -8, "error_note": "Error in request from click"}


# --------------------------------------------------------------------------- #
# Non-POST                                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [PREPARE_URL, COMPLETE_URL])
async def test_non_post_get_is_minus8(integration_client: AsyncClient, url: str) -> None:
    r = await integration_client.get(url)
    assert r.status_code == 200
    assert r.json() == {"error": -8, "error_note": "Error in request from click"}


async def test_non_post_put_is_minus8(integration_client: AsyncClient) -> None:
    r = await integration_client.put(PREPARE_URL)
    assert r.status_code == 200
    assert r.json() == {"error": -8, "error_note": "Error in request from click"}


# --------------------------------------------------------------------------- #
# Pre-charge geo veto (ADR-0063), enforcement point A                          #
# --------------------------------------------------------------------------- #


async def test_prepare_refuses_a_foreign_guest_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A guest order with evidence saying the buyer is not at home.

    The refusal must be exactly the error ``/prepare`` already returns for a
    non-``pending_payment`` order (-9), indistinguishable from any other
    unpayable order, and no transaction row may exist afterwards. A repeat of
    the exact same call must still leave exactly one audit event behind.
    """
    order_id = await _seed_guest_order_with_evidence(db_session, ip_country="NL")
    click_trans_id = "9100"

    for _ in range(2):
        r = await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
        assert r.status_code == 200
        resp = r.json()
        assert resp["error"] == -9
        assert resp["error_note"] == "Transaction cancelled"

    txn = (
        await db_session.execute(
            select(ClickTransaction).where(ClickTransaction.click_trans_id == int(click_trans_id))
        )
    ).scalar_one_or_none()
    assert txn is None
    kinds = [
        e.kind
        for e in (
            await db_session.execute(select(OrderEvent).where(OrderEvent.order_id == order_id))
        ).scalars()
    ]
    assert kinds.count("order.precharge_vetoed") == 1


async def test_prepare_passes_a_home_guest_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The mirror case: same shape, home country — proceeds exactly as today."""
    order_id = await _seed_guest_order_with_evidence(db_session, ip_country="UZ")

    r = await integration_client.post(
        PREPARE_URL,
        data=_prepare_body(click_trans_id="9101", merchant_trans_id=order_id),
    )
    assert r.status_code == 200
    prepared = r.json()
    assert prepared["error"] == 0
    assert prepared["error_note"] == "Success"
