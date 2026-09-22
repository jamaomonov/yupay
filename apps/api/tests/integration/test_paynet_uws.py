"""End-to-end tests for the Paynet UWS JSON-RPC endpoint.

These drive the mounted app over HTTP the way Paynet's terminal network does:
one ``POST /api/v1/payments/paynet/uws`` carrying Basic auth and a JSON-RPC 2.0
envelope.

Two rules from the spec are asserted here because they are the ones easiest to
get wrong by copying Payme:

* **Bad credentials are HTTP 401**, not a 200 with an error body. Paynet says so
  in as many words, and Payme says the exact opposite.
* **An unknown transaction in ``CheckTransaction`` is a success**, carrying
  ``transactionState: 3``. Answering ``203`` there turns a routine "do you know
  this?" into an incident.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import _round_to_payable
from yupay.modules.payments.models import Payment
from yupay.modules.paynet.models import PaynetTransaction
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

#: Re-stated rather than imported from the module under test, on purpose:
#: GMT+5 is what the contract fixes, so the assertion should fail if the
#: implementation ever drifts from it. (Importing ``paynet.service`` here would
#: also pull ``payments.service`` before the app package is initialised.)
TASHKENT = timezone(timedelta(hours=5))

UWS_URL = "/api/v1/payments/paynet/uws"
USERNAME = "paynet"
PASSWORD = "uws-test-password"
SERVICE_ID = 7
# 130000.00 UZS * 100
EXPECTED_TIYIN = 13_000_000


@pytest.fixture(autouse=True)
def _paynet_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYNET_USERNAME", USERNAME)
    monkeypatch.setenv("PAYNET_PASSWORD", PASSWORD)
    monkeypatch.setenv("PAYNET_SERVICE_ID", str(SERVICE_ID))
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _auth(user: str = USERNAME, password: str = PASSWORD) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _rpc(method: str, params: dict[str, Any], req_id: object = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}


async def _seed_order(
    db: AsyncSession,
    *,
    status: str = "pending_payment",
    total_charged: Decimal = Decimal("130000.00"),
    expires_in: timedelta = timedelta(minutes=30),
) -> str:
    user_id, order_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            status=status,
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=total_charged,
            expires_at=datetime.now(UTC) + expires_in,
        )
    )
    await db.commit()
    return order_id


async def _perform(
    client: AsyncClient, order_id: str, *, transaction_id: int, amount: int = EXPECTED_TIYIN
) -> dict[str, Any]:
    response = await client.post(
        UWS_URL,
        json=_rpc(
            "PerformTransaction",
            {
                "serviceId": SERVICE_ID,
                "transactionId": transaction_id,
                "amount": amount,
                "fields": {"order_id": order_id},
            },
        ),
        headers=_auth(),
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- auth -------------------------------------------------------------------


async def test_missing_credentials_are_401_not_a_json_rpc_error(
    integration_client: AsyncClient,
) -> None:
    # The spec is explicit that this must not be a 200 with an error body.
    response = await integration_client.post(UWS_URL, json=_rpc("GetInformation", {}))
    assert response.status_code == 401


async def test_wrong_password_is_401(integration_client: AsyncClient) -> None:
    response = await integration_client.post(
        UWS_URL, json=_rpc("GetInformation", {}), headers=_auth(password="nope")
    )
    assert response.status_code == 401


async def test_unconfigured_integration_refuses_everything(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A blank deployment must never accept a blank presented credential.
    monkeypatch.setenv("PAYNET_PASSWORD", "")
    cfg.get_settings.cache_clear()
    response = await integration_client.post(
        UWS_URL, json=_rpc("GetInformation", {}), headers=_auth(password="")
    )
    assert response.status_code == 401


# --- GetInformation ---------------------------------------------------------


async def test_get_information_returns_the_exact_amount_owed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("GetInformation", {"serviceId": SERVICE_ID, "fields": {"order_id": order_id}}),
        headers=_auth(),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    # String, not int/number (2026-09-22, Paynet certification feedback).
    assert result["status"] == "0"
    # Soʻm, not tiyin: 13_000_000 tiyin / 100 = 130_000 soʻm — unlike
    # PerformTransaction's `amount` param, which the spec fixes in tiyin.
    assert result["fields"]["amount"] == "130000"
    assert result["fields"]["order_id"] == order_id
    # GMT+5, "YYYY-MM-dd HH:mm:ss" — the format every method but one uses.
    datetime.strptime(result["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TASHKENT)


async def test_unknown_order_is_302(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    del db_session
    response = await integration_client.post(
        UWS_URL,
        json=_rpc(
            "GetInformation", {"serviceId": SERVICE_ID, "fields": {"order_id": str(uuid.uuid4())}}
        ),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 302


async def test_a_malformed_order_id_is_302_not_a_500(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    del db_session
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("GetInformation", {"serviceId": SERVICE_ID, "fields": {"order_id": "не-uuid"}}),
        headers=_auth(),
    )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == 302


async def test_get_information_on_a_paid_order_is_302_not_201(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A settled bill has nothing left to show a payer, so ``GetInformation``
    answers the same as "no such order" (2026-09-22, Paynet certification
    feedback) — unlike ``PerformTransaction``, which keeps 201 for the same
    order because a client actively trying to pay is owed the reason.
    See :func:`test_a_second_transaction_on_a_paid_order_is_201` below.
    """
    paid = await _seed_order(db_session, status="paid")
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("GetInformation", {"serviceId": SERVICE_ID, "fields": {"order_id": paid}}),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 302


async def test_an_expired_order_is_501(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Distinct from both "no such order" (302) and "already paid": the two
    # need different answers from support — "check the number" versus
    # "place the order again" — so they must not collapse into one code.
    expired = await _seed_order(db_session, expires_in=timedelta(minutes=-5))
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("GetInformation", {"serviceId": SERVICE_ID, "fields": {"order_id": expired}}),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 501


async def test_a_uzs_order_total_is_always_whole_som(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Paynet cannot collect a fraction of a soʻm, so we must never quote one.

    Asked on 2026-09-22 whether they wanted ``"1300.5"`` or ``"1300.50"``,
    Paynet answered neither: *"желательно целой, у нас нету возможности
    оплатить дробную часть"*. We already satisfy that, and not by accident —
    ``orders.service._round_to_payable`` quantizes UZS to
    ``_CURRENCY_QUANTUM["UZS"] == Decimal("1")``, whole soʻm, before the total
    is ever stored.

    This asserts the property at the only place it is externally visible, so
    that adding a sub-soʻm quantum for UZS breaks *here* — where the
    consequence is a payment Paynet refuses — and not silently in an FX
    change nobody connects to an acquirer.
    """
    order_id = await _seed_order(
        db_session, total_charged=_round_to_payable(Decimal("1300.4999"), "UZS")
    )
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("GetInformation", {"serviceId": SERVICE_ID, "fields": {"order_id": order_id}}),
        headers=_auth(),
    )
    amount = response.json()["result"]["fields"]["amount"]
    assert "." not in amount, f"Paynet cannot collect {amount} soʻm"
    assert amount == "1300"


async def test_a_foreign_service_id_is_305(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("GetInformation", {"serviceId": 999, "fields": {"order_id": order_id}}),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 305


# --- PerformTransaction -----------------------------------------------------


async def test_perform_settles_the_order_and_returns_an_integer_provider_id(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)

    body = await _perform(integration_client, order_id, transaction_id=90_001)

    result = body["result"]
    # Paynet types providerTrnId as int64; our order ids are UUIDs, so this
    # number comes from a sequence of its own.
    assert isinstance(result["providerTrnId"], int)
    assert result["providerTrnId"] >= 1000
    assert result["fields"]["order_id"] == order_id

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    # "paid" is the transition; settlement starts fulfilment in the same
    # request, so the order may already have moved past it by the time we look.
    assert order.status in {"paid", "fulfilling", "fulfilled", "delivered"}
    payment = (
        await db_session.execute(select(Payment).where(Payment.order_id == order_id))
    ).scalar_one()
    assert payment.provider == "paynet"
    assert payment.status == "succeeded"


async def test_a_replayed_transaction_id_is_201_not_a_silent_success(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A ``transactionId`` we already hold answers 201 — "Транзакция уже
    существует" — rather than re-echoing the original 200 (2026-09-22,
    Paynet certification feedback: their own checklist sends this exact call
    twice and expects the error). The money still moves exactly once either
    way; only the response shape changed.
    """
    order_id = await _seed_order(db_session)

    first = await _perform(integration_client, order_id, transaction_id=90_002)
    assert "result" in first, first

    second = await integration_client.post(
        UWS_URL,
        json=_rpc(
            "PerformTransaction",
            {
                "serviceId": SERVICE_ID,
                "transactionId": 90_002,
                "amount": EXPECTED_TIYIN,
                "fields": {"order_id": order_id},
            },
        ),
        headers=_auth(),
    )
    assert second.json()["error"]["code"] == 201

    rows = (
        await db_session.execute(select(func.count()).select_from(PaynetTransaction))
    ).scalar_one()
    assert rows == 1


async def test_a_duplicate_that_races_past_the_lookup_is_201_not_32603(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The same duplicate, arriving concurrently instead of sequentially.

    Two calls can both pass the ``_find`` lookup before either has flushed;
    the unique index then rejects the loser. That must answer ``201`` like
    the sequential case rather than falling through to ``-32603``, because on
    Paynet's retry-happy network it is an ordinary event, not a protocol
    failure. Simulated by pre-inserting the row the way the winner would have,
    which is exactly the state the loser flushes into.
    """
    order_id = await _seed_order(db_session)
    db_session.add(
        PaynetTransaction(
            id=str(uuid.uuid4()),
            paynet_transaction_id=90_011,
            order_id=order_id,
            payment_id=None,
            amount_tiyin=EXPECTED_TIYIN,
            service_id=SERVICE_ID,
            state=1,
            performed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    body = await _perform(integration_client, order_id, transaction_id=90_011)
    assert body["error"]["code"] == 201


async def test_an_amount_that_does_not_match_the_order_is_413(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # The amount rides in the deep link, but nothing stops a crafted call.
    order_id = await _seed_order(db_session)
    body = await _perform(integration_client, order_id, transaction_id=90_003, amount=1)
    assert body["error"]["code"] == 413
    rows = (
        await db_session.execute(select(func.count()).select_from(PaynetTransaction))
    ).scalar_one()
    assert rows == 0


async def test_a_second_transaction_on_a_paid_order_is_201(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    await _perform(integration_client, order_id, transaction_id=90_004)

    body = await _perform(integration_client, order_id, transaction_id=90_005)
    assert body["error"]["code"] == 201


# --- CheckTransaction -------------------------------------------------------


async def test_check_reports_state_1_after_a_payment(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    performed = await _perform(integration_client, order_id, transaction_id=90_006)

    response = await integration_client.post(
        UWS_URL,
        json=_rpc(
            "CheckTransaction",
            {
                "serviceId": SERVICE_ID,
                "transactionId": 90_006,
                # This method alone carries the legacy format, and we accept it
                # without reading it.
                "timestamp": "Mon Jun 16 06:12:41 UZT 2021",
            },
        ),
        headers=_auth(),
    )

    result = response.json()["result"]
    assert result["transactionState"] == 1
    assert result["providerTrnId"] == performed["result"]["providerTrnId"]


async def test_check_on_an_unknown_transaction_is_a_success_with_state_3(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    del db_session
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("CheckTransaction", {"serviceId": SERVICE_ID, "transactionId": 40_404}),
        headers=_auth(),
    )

    body = response.json()
    assert "error" not in body, "an unknown transaction is not an error here"
    assert body["result"]["transactionState"] == 3


# --- CancelTransaction ------------------------------------------------------


async def test_cancel_reverses_a_payment_and_is_idempotent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    await _perform(integration_client, order_id, transaction_id=90_007)

    payload = _rpc("CancelTransaction", {"serviceId": SERVICE_ID, "transactionId": 90_007})
    first = (await integration_client.post(UWS_URL, json=payload, headers=_auth())).json()
    second = (await integration_client.post(UWS_URL, json=payload, headers=_auth())).json()

    assert first["result"]["transactionState"] == 2
    # A retry is far likelier than a second intent, so it echoes rather than
    # erroring — and must never reverse twice.
    assert second["result"] == first["result"]
    payment = (
        await db_session.execute(select(Payment).where(Payment.order_id == order_id))
    ).scalar_one()
    await db_session.refresh(payment)
    assert payment.status == "refunded"


async def test_cancel_on_an_unknown_transaction_is_203(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    del db_session
    response = await integration_client.post(
        UWS_URL,
        json=_rpc("CancelTransaction", {"serviceId": SERVICE_ID, "transactionId": 40_405}),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 203


async def test_cancel_is_refused_once_the_goods_are_delivered(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    await _perform(integration_client, order_id, transaction_id=90_008)
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    order.status = "delivered"
    await db_session.commit()

    response = await integration_client.post(
        UWS_URL,
        json=_rpc("CancelTransaction", {"serviceId": SERVICE_ID, "transactionId": 90_008}),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 306


# --- GetStatement -----------------------------------------------------------


async def test_statement_lists_successful_transactions_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    kept = await _seed_order(db_session)
    dropped = await _seed_order(db_session)
    await _perform(integration_client, kept, transaction_id=90_009)
    await _perform(integration_client, dropped, transaction_id=90_010)
    await integration_client.post(
        UWS_URL,
        json=_rpc("CancelTransaction", {"serviceId": SERVICE_ID, "transactionId": 90_010}),
        headers=_auth(),
    )

    window = datetime.now(UTC).astimezone(TASHKENT)
    response = await integration_client.post(
        UWS_URL,
        json=_rpc(
            "GetStatement",
            {
                "serviceId": SERVICE_ID,
                "dateFrom": (window - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "dateTo": (window + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
            },
        ),
        headers=_auth(),
    )

    statements = response.json()["result"]["statements"]
    # A cancelled row here would read as money we claim to hold and do not.
    assert [row["transactionId"] for row in statements] == [90_009]
    assert statements[0]["amount"] == EXPECTED_TIYIN
    # int, not a string (2026-09-22, Paynet asked to confirm this explicitly)
    # — already true, since a string here would have failed the equality
    # check two lines up against a bare Python int.
    assert isinstance(statements[0]["transactionId"], int)


async def test_a_bad_statement_window_is_414(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    del db_session
    response = await integration_client.post(
        UWS_URL,
        json=_rpc(
            "GetStatement",
            {"serviceId": SERVICE_ID, "dateFrom": "20.04.2021 08:00:00", "dateTo": "nonsense"},
        ),
        headers=_auth(),
    )
    assert response.json()["error"]["code"] == 414


# --- transport --------------------------------------------------------------


async def test_a_non_json_body_is_32700(integration_client: AsyncClient) -> None:
    response = await integration_client.post(UWS_URL, content=b"not json", headers=_auth())
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32700


async def test_an_unknown_method_is_32601(integration_client: AsyncClient) -> None:
    response = await integration_client.post(
        UWS_URL, json=_rpc("Whatever", {"serviceId": SERVICE_ID}), headers=_auth()
    )
    assert response.json()["error"]["code"] == -32601


async def test_a_missing_required_param_is_32600(integration_client: AsyncClient) -> None:
    response = await integration_client.post(
        UWS_URL, json=_rpc("PerformTransaction", {"serviceId": SERVICE_ID}), headers=_auth()
    )
    assert response.json()["error"]["code"] == -32600


async def test_a_get_is_32300_in_the_body_not_a_405(integration_client: AsyncClient) -> None:
    response = await integration_client.get(UWS_URL, headers=_auth())
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32300


async def test_the_request_id_is_echoed_verbatim(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_order(db_session)
    response = await integration_client.post(
        UWS_URL,
        json=_rpc(
            "GetInformation",
            {"serviceId": SERVICE_ID, "fields": {"order_id": order_id}},
            req_id="abc-123",
        ),
        headers=_auth(),
    )
    assert response.json()["id"] == "abc-123"
