"""End-to-end tests for the Payme (Paycom) JSON-RPC merchant endpoint.

These drive the mounted FastAPI app over HTTP exactly as Payme's sandbox does:
a single ``POST /api/v1/payments/payme/merchant`` carrying Basic auth and a
JSON-RPC 2.0 envelope. The two mandatory sandbox sequences are exercised whole
(unconfirmed cancel + confirmed cancel), alongside the transport-level failures
Payme probes for — wrong auth (-32504), non-JSON body (-32700), unknown method
(-32601), a GET (-32300) — plus idempotent replay of Create/Perform/Cancel.

Every response, success or failure, is HTTP 200: Payme reads any non-200 as a
transport error (-32400), so the wire contract lives entirely in the JSON body.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

MERCHANT_URL = "/api/v1/payments/payme/merchant"
PAYME_LOGIN = "Paycom"
TEST_KEY = "test-sandbox-key-xyz"
# 130000.00 UZS * 100 = 13_000_000 tiyin
EXPECTED_TIYIN = 13_000_000


@pytest.fixture(autouse=True)
def _payme_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYME_LOGIN", PAYME_LOGIN)
    monkeypatch.setenv("PAYME_TEST_KEY", TEST_KEY)
    monkeypatch.setenv("PAYME_KEY", "prod-cabinet-key")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _auth(key: str = TEST_KEY, login: str = PAYME_LOGIN) -> dict[str, str]:
    token = base64.b64encode(f"{login}:{key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _rpc(method: str, params: dict[str, object], req_id: object = 1) -> dict[str, object]:
    return {"method": method, "params": params, "id": req_id}


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


async def _count_txns(db: AsyncSession, payme_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(PaymeTransaction)
            .where(PaymeTransaction.payme_id == payme_id)
        )
    ).scalar_one()


async def _seed_guest_order_with_evidence(
    db: AsyncSession,
    *,
    ip_country: str,
    total_charged: Decimal = Decimal("130000.00"),
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


# --------------------------------------------------------------------------- #
# Mandatory sandbox sequence 1: unconfirmed (create → cancel before perform)   #
# --------------------------------------------------------------------------- #


async def test_sandbox_sequence_unconfirmed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)

    # Wrong auth is rejected with -32504 (HTTP 200).
    bad = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(key="wrong-key"),
        json=_rpc("CheckPerformTransaction", {"amount": EXPECTED_TIYIN, "account": {}}),
    )
    assert bad.status_code == 200
    assert bad.json()["error"]["code"] == -32504

    # Bad amount -> -31001.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CheckPerformTransaction",
            {"amount": EXPECTED_TIYIN + 1, "account": {"order_id": order_id}},
        ),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -31001

    # Unknown account -> -31050.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CheckPerformTransaction",
            {"amount": EXPECTED_TIYIN, "account": {"order_id": str(uuid.uuid4())}},
        ),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -31050

    # CheckPerformTransaction (ok).
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CheckPerformTransaction",
            {"amount": EXPECTED_TIYIN, "account": {"order_id": order_id}},
        ),
    )
    assert r.status_code == 200
    assert r.json()["result"] == {"allow": True}

    # CreateTransaction -> state 1.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CreateTransaction",
            {
                "id": "seq1-tx",
                "time": 1_700_000_000_000,
                "amount": EXPECTED_TIYIN,
                "account": {"order_id": order_id},
            },
        ),
    )
    assert r.status_code == 200
    created = r.json()["result"]
    assert created["state"] == 1
    assert created["create_time"] == 1_700_000_000_000

    # CancelTransaction -> state -1.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc("CancelTransaction", {"id": "seq1-tx", "reason": 1}),
    )
    assert r.status_code == 200
    cancelled = r.json()["result"]
    assert cancelled["state"] == -1
    assert cancelled["transaction"] == created["transaction"]

    # DB reflects the pending-cancel (payment cancelled, order still payable).
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "pending_payment"


# --------------------------------------------------------------------------- #
# Mandatory sandbox sequence 2: confirmed (create → perform → cancel/refund)   #
# --------------------------------------------------------------------------- #


async def test_sandbox_sequence_confirmed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)

    # CheckPerformTransaction (ok).
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CheckPerformTransaction",
            {"amount": EXPECTED_TIYIN, "account": {"order_id": order_id}},
        ),
    )
    assert r.status_code == 200
    assert r.json()["result"] == {"allow": True}

    # CreateTransaction -> state 1.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CreateTransaction",
            {
                "id": "seq2-tx",
                "time": 1_700_000_000_000,
                "amount": EXPECTED_TIYIN,
                "account": {"order_id": order_id},
            },
        ),
    )
    assert r.status_code == 200
    assert r.json()["result"]["state"] == 1

    # PerformTransaction -> state 2; order is paid.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc("PerformTransaction", {"id": "seq2-tx"}),
    )
    assert r.status_code == 200
    performed = r.json()["result"]
    assert performed["state"] == 2
    assert performed["perform_time"] > 0

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status != "pending_payment"
    assert order.paid_at is not None
    payment = (
        await db_session.execute(
            select(Payment).where(Payment.order_id == order_id, Payment.provider == "payme")
        )
    ).scalar_one()
    assert payment.status == "succeeded"
    payment_id = payment.id

    # CancelTransaction on the performed tx -> state -2, refund reconciled.
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc("CancelTransaction", {"id": "seq2-tx", "reason": 5}),
    )
    assert r.status_code == 200
    assert r.json()["result"]["state"] == -2

    db_session.expire_all()
    payment = (
        await db_session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    assert payment.status == "refunded"
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status == "refunded"


# --------------------------------------------------------------------------- #
# Transport-level failures                                                     #
# --------------------------------------------------------------------------- #


async def test_non_json_body_is_32700(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        MERCHANT_URL,
        headers={**_auth(), "content-type": "application/json"},
        content=b"not json at all {",
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32700


async def test_unknown_method_is_32601(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc("NoSuchMethod", {}),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32601


async def test_missing_required_param_is_32600(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        # CheckPerformTransaction with no ``amount``.
        json=_rpc("CheckPerformTransaction", {"account": {"order_id": "x"}}),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32600


async def test_get_is_32300(integration_client: AsyncClient) -> None:
    r = await integration_client.get(MERCHANT_URL, headers=_auth())
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32300


async def test_missing_auth_header_is_32504(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        MERCHANT_URL,
        json=_rpc("CheckPerformTransaction", {"amount": 1, "account": {}}),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32504


async def test_id_is_echoed(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc("NoSuchMethod", {}, req_id="rpc-abc-123"),
    )
    assert r.status_code == 200
    assert r.json()["id"] == "rpc-abc-123"


# --------------------------------------------------------------------------- #
# Idempotent replay over HTTP                                                  #
# --------------------------------------------------------------------------- #


async def test_replay_create_perform_cancel_is_idempotent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    create_req = _rpc(
        "CreateTransaction",
        {
            "id": "replay-tx",
            "time": 1_700_000_000_000,
            "amount": EXPECTED_TIYIN,
            "account": {"order_id": order_id},
        },
    )

    first = await integration_client.post(MERCHANT_URL, headers=_auth(), json=create_req)
    second = await integration_client.post(MERCHANT_URL, headers=_auth(), json=create_req)
    assert first.status_code == second.status_code == 200
    assert first.json()["result"] == second.json()["result"]
    assert await _count_txns(db_session, "replay-tx") == 1

    perform_req = _rpc("PerformTransaction", {"id": "replay-tx"})
    p1 = await integration_client.post(MERCHANT_URL, headers=_auth(), json=perform_req)
    p2 = await integration_client.post(MERCHANT_URL, headers=_auth(), json=perform_req)
    assert p1.json()["result"] == p2.json()["result"]

    cancel_req = _rpc("CancelTransaction", {"id": "replay-tx", "reason": 5})
    c1 = await integration_client.post(MERCHANT_URL, headers=_auth(), json=cancel_req)
    c2 = await integration_client.post(MERCHANT_URL, headers=_auth(), json=cancel_req)
    assert c1.json()["result"] == c2.json()["result"]

    # Still exactly one row after all the replays.
    assert await _count_txns(db_session, "replay-tx") == 1


async def test_commit_failure_is_32400_not_500(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit-time infra failure must render as -32400 at HTTP 200, not a 500.

    Payme reads any non-200 as a transport error, so even a broken commit (e.g.
    the connection dropping after the handler's flush) has to come back as a
    JSON-RPC error body — never escape the route as an HTTP 500.
    """
    order_id = await _seed_order(db_session)

    # Force the FIRST commit to blow up — that is the route's own
    # ``await db.commit()``. Later commits (the ``get_session`` dependency's
    # trailing commit during teardown) delegate to the real implementation, so
    # the failure we're testing is strictly the route's, not an artefact of the
    # session-dependency layer.
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    real_commit = _AsyncSession.commit
    calls = {"n": 0}

    async def _flaky_commit(self: _AsyncSession) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset during commit")
        await real_commit(self)

    monkeypatch.setattr(_AsyncSession, "commit", _flaky_commit, raising=True)

    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CreateTransaction",
            {
                "id": "commit-fail-tx",
                "time": 1_700_000_000_000,
                "amount": EXPECTED_TIYIN,
                "account": {"order_id": order_id},
            },
        ),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32400


# --------------------------------------------------------------------------- #
# Pre-charge geo veto (ADR-0063), enforcement point A                          #
# --------------------------------------------------------------------------- #


async def test_check_perform_refuses_a_foreign_guest_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A guest order with evidence saying the buyer is not at home.

    The refusal must be Payme's own -31051 — indistinguishable from any other
    unpayable order — and no transaction row may exist afterwards. A repeat of
    the exact same call must still leave exactly one audit event behind.
    """
    order_id = await _seed_guest_order_with_evidence(db_session, ip_country="NL")

    for _ in range(2):
        r = await integration_client.post(
            MERCHANT_URL,
            headers=_auth(),
            json=_rpc(
                "CheckPerformTransaction",
                {"amount": EXPECTED_TIYIN, "account": {"order_id": order_id}},
            ),
        )
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -31051

    txn = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.order_id == order_id)
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


async def test_check_perform_passes_a_home_guest_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The mirror case: same shape, home country — proceeds exactly as today."""
    order_id = await _seed_guest_order_with_evidence(db_session, ip_country="UZ")

    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CheckPerformTransaction",
            {"amount": EXPECTED_TIYIN, "account": {"order_id": order_id}},
        ),
    )
    assert r.status_code == 200
    assert r.json()["result"] == {"allow": True}


async def test_create_transaction_refuses_a_foreign_guest_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """IMPORTANT (I5b): the veto's other Payme call site. `CreateTransaction`
    runs `_check_perform` then `_refuse_if_vetoed` before ever creating a
    transaction row -- same -31051, same "no row" guarantee as
    `CheckPerformTransaction` above (`test_check_perform_refuses_a_foreign_guest_order`)."""
    order_id = await _seed_guest_order_with_evidence(db_session, ip_country="NL")

    r = await integration_client.post(
        MERCHANT_URL,
        headers=_auth(),
        json=_rpc(
            "CreateTransaction",
            {
                "id": "veto-create-tx",
                "time": 1_700_000_000_000,
                "amount": EXPECTED_TIYIN,
                "account": {"order_id": order_id},
            },
        ),
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -31051

    txn = (
        await db_session.execute(
            select(PaymeTransaction).where(PaymeTransaction.order_id == order_id)
        )
    ).scalar_one_or_none()
    assert txn is None
