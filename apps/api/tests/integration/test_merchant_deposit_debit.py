"""``POST /api/v1/admin/merchants/{id}/deposit-debits`` — the fourth movement.

The operator's correction: taking money back off a merchant's prepaid
balance. Exercised through the mounted app with real admin auth, because the
parts that can be wrong are the route's (the namespaced key, the echoed
amount, the refusals) and not the posting's.

What each test is here to catch:

- the balance actually drops, and by the posted amount;
- a retry under one key books nothing the second time — the shape an operator
  produces by double-clicking a form after a timeout;
- a debit may not overdraw, because a negative deposit is a debt with no
  mechanism behind it;
- a blank or missing reason is refused, because the ledger row is the only
  record of why a balance fell;
- the movement lands on the audit trail with its reason readable — the
  writer/reader pair the module README keeps warning about.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.idempotency import MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

_PATH = "/api/v1/admin/merchants/{}/deposit-debits"
BOT_TOKEN = "123456:TEST"

# Telegram id 98: every integration module that needs an admin mints its own
# (91-97, 4242, 4343 are taken), because `admin_headers` is a per-file fixture
# rather than a conftest one. The suite runs under `-n auto`, so two files
# sharing an id would be two workers racing for the same user row.
_ADMIN_TG_ID = 98


def _key(name: str) -> str:
    """An Idempotency-Key that the endpoint will actually accept.

    The endpoint refuses anything under ``MIN_IDEMPOTENCY_KEY_LENGTH``, and a
    key one character short answers ``422`` — which is indistinguishable, from
    the test's side, from the endpoint being broken. Every key in this file
    goes through here, and the floor is imported rather than copied so the two
    cannot drift apart.
    """
    assert len(name) >= MIN_IDEMPOTENCY_KEY_LENGTH, (
        f"test key {name!r} is {len(name)} chars, under the endpoint's {MIN_IDEMPOTENCY_KEY_LENGTH}"
    )
    return name


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": _ADMIN_TG_ID, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == _ADMIN_TG_ID)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _create_merchant(client: AsyncClient, headers: dict[str, str], title: str) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _credit(
    client: AsyncClient, headers: dict[str, str], merchant_id: str, amount: str, key: str
) -> None:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": _key(key)},
        json={"amount": amount, "note": "funding"},
    )
    assert r.status_code == 201, r.text


async def _balance(client: AsyncClient, headers: dict[str, str], merchant_id: str) -> Decimal:
    r = await client.get("/api/v1/admin/merchants", headers=headers)
    assert r.status_code == 200, r.text
    by_id = {m["id"]: m for m in r.json()["items"]}
    return Decimal(str(by_id[merchant_id]["deposit_balance"]))


async def test_a_debit_lowers_the_balance_by_its_amount(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant = await _create_merchant(integration_client, admin_headers, "Debit me")
    await _credit(integration_client, admin_headers, merchant, "10.00", _key("debit-test-credit-1"))

    r = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key("debit-deposit-0001")},
        json={"amount": "4.00", "reason": "credited in error"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["amount"])) == Decimal("4.00")
    assert Decimal(str(body["balance"])) == Decimal("6.00")
    assert await _balance(integration_client, admin_headers, merchant) == Decimal("6.00")


async def test_the_whole_balance_can_be_taken_to_zero(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The case this endpoint was built for: zeroing a balance exactly."""
    merchant = await _create_merchant(integration_client, admin_headers, "Zero me")
    await _credit(integration_client, admin_headers, merchant, "1.10", _key("debit-test-credit-2"))

    r = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key("debit-deposit-0002")},
        json={"amount": "1.10", "reason": "test balance, zeroed"},
    )
    assert r.status_code == 201, r.text
    assert Decimal(str(r.json()["balance"])) == Decimal("0")
    assert await _balance(integration_client, admin_headers, merchant) == Decimal("0")


async def test_a_replayed_key_books_nothing_and_echoes_the_first_amount(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The double-click after a timeout. The ledger replays by key alone.

    The second call deliberately sends a DIFFERENT amount: ``post()`` does not
    compare parameters, so it returns the original transaction, and the
    response echoing ``2.00`` rather than the requested ``5.00`` is what makes
    that visible to the operator instead of silent.
    """
    merchant = await _create_merchant(integration_client, admin_headers, "Replay")
    await _credit(integration_client, admin_headers, merchant, "10.00", _key("debit-test-credit-3"))
    key = "debit-test-replay-0003"

    first = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key(key)},
        json={"amount": "2.00", "reason": "correction"},
    )
    assert first.status_code == 201, first.text
    second = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key(key)},
        json={"amount": "5.00", "reason": "correction"},
    )
    assert second.status_code == 201, second.text

    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    assert Decimal(str(second.json()["amount"])) == Decimal("2.00")
    assert await _balance(integration_client, admin_headers, merchant) == Decimal("8.00")


async def test_a_debit_may_not_overdraw_the_deposit(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """A negative deposit is a debt with nothing behind it, so it is refused."""
    merchant = await _create_merchant(integration_client, admin_headers, "Overdraw")
    await _credit(integration_client, admin_headers, merchant, "3.00", _key("debit-test-credit-4"))

    r = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key("debit-deposit-0004")},
        json={"amount": "3.01", "reason": "too much"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "insufficient_deposit"
    assert await _balance(integration_client, admin_headers, merchant) == Decimal("3.00")


async def test_an_empty_deposit_refuses_rather_than_going_negative(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """No account exists yet — the read creates none, and the debit refuses."""
    merchant = await _create_merchant(integration_client, admin_headers, "Never funded")
    r = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key("debit-deposit-0005")},
        json={"amount": "0.01", "reason": "nothing there"},
    )
    assert r.status_code == 409, r.text
    assert await _balance(integration_client, admin_headers, merchant) == Decimal("0")


@pytest.mark.parametrize("reason", ["", "   "])
async def test_a_blank_reason_is_refused(
    integration_client: AsyncClient, admin_headers: dict[str, str], reason: str
) -> None:
    """The ledger row is the only record of why a balance fell."""
    merchant = await _create_merchant(integration_client, admin_headers, "No reason")
    await _credit(
        integration_client, admin_headers, merchant, "5.00", f"debit-deposit-credit-{len(reason)}"
    )

    r = await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key(f"debit-deposit-blank-{len(reason)}")},
        json={"amount": "1.00", "reason": reason},
    )
    assert r.status_code in (400, 422), r.text
    assert await _balance(integration_client, admin_headers, merchant) == Decimal("5.00")


async def test_a_missing_idempotency_key_is_refused(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant = await _create_merchant(integration_client, admin_headers, "No key")
    r = await integration_client.post(
        _PATH.format(merchant),
        headers=admin_headers,
        json={"amount": "1.00", "reason": "correction"},
    )
    assert r.status_code in (400, 422), r.text


async def test_the_reason_is_readable_on_the_audit_trail(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The writer/reader pair: a reason stored under the wrong metadata key
    moves the money and shows a blank line here."""
    merchant = await _create_merchant(integration_client, admin_headers, "Audit")
    await _credit(integration_client, admin_headers, merchant, "6.00", _key("debit-test-credit-6"))
    await integration_client.post(
        _PATH.format(merchant),
        headers={**admin_headers, "Idempotency-Key": _key("debit-deposit-0006")},
        json={"amount": "6.00", "reason": "wrong merchant funded"},
    )

    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant}/transactions", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    debits = [t for t in r.json()["items"] if t["kind"] == "merchant_deposit_debit"]
    assert len(debits) == 1, r.text
    assert debits[0]["note"] == "wrong merchant funded"
    # Signed delta: the balance went DOWN, so the statement must say so.
    assert Decimal(str(debits[0]["amount"])) == Decimal("-6.00")


async def test_the_endpoint_needs_an_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        _PATH.format("whoever"), json={"amount": "1.00", "reason": "x"}
    )
    assert r.status_code == 401
