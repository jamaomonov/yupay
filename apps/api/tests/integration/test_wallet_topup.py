"""Customer wallet top-up: 1:1 deposit via an acquirer (ADR-0058)."""

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
from yupay.modules.orders.models import Order
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet import service as wallet_svc
from yupay.modules.wallet.service import Leg

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> tuple[str, str]:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


async def _topup(
    client: AsyncClient, *, token: str, amount: str, provider: str, key: str
) -> dict[str, object]:
    r = await client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": amount, "provider": provider},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def _settle_mock(client: AsyncClient, payment: dict[str, object]) -> None:
    r = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt-{payment['id']}",
                "payment_id": payment["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 200, r.text


def _wallet_uzs(overview: dict[str, object]) -> Decimal:
    balances = overview["balances"]
    assert isinstance(balances, list)
    for row in balances:
        assert isinstance(row, dict)
        if row.get("kind") == "user_wallet" and row.get("currency") == "UZS":
            return Decimal(str(row["balance"]))
    return Decimal("0")


async def test_topup_rejects_wallet_provider(integration_client: AsyncClient) -> None:
    token, _ = await _login_user(integration_client, tg_id=901)
    r = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-topup-reject-wallet",
        },
        json={"amount": "10000", "provider": "wallet"},
    )
    assert r.status_code == 422


async def test_topup_rejects_amount_below_min(integration_client: AsyncClient) -> None:
    token, _ = await _login_user(integration_client, tg_id=902)
    r = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-topup-reject-minxx",
        },
        json={"amount": "9999", "provider": "mock"},
    )
    assert r.status_code == 422


async def test_topup_settle_credits_once(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _user_id = await _login_user(integration_client, tg_id=903)
    first = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-once-aaa",
    )
    replay = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-once-aaa",
    )
    assert first["id"] == replay["id"]
    order_id = first["order_id"]
    assert isinstance(order_id, str)

    await _settle_mock(integration_client, first)

    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert wallet.status_code == 200
    assert _wallet_uzs(wallet.json()) == Decimal("10000")

    order = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert order.status_code == 200
    body = order.json()
    assert body["purpose"] == "wallet_topup"
    assert body["status"] == "delivered"
    assert body["items"] == []

    listing = await integration_client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {token}"}
    )
    assert listing.status_code == 200
    assert all(row["id"] != order_id for row in listing.json()["items"])

    await _settle_mock(integration_client, first)
    wallet2 = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert _wallet_uzs(wallet2.json()) == Decimal("10000")


async def test_topup_refund_reverses_when_unspent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _ = await _login_user(integration_client, tg_id=906)
    payment = await _topup(
        integration_client,
        token=token,
        amount="25000",
        provider="mock",
        key="wallet-topup-refund-ok",
    )
    await _settle_mock(integration_client, payment)

    admin, _ = await _login_user(integration_client, tg_id=907)
    await _grant_admin(db_session, tg_id=907)
    refund = await integration_client.post(
        f"/api/v1/admin/payments/{payment['id']}/refund",
        headers={
            "Authorization": f"Bearer {admin}",
            "Idempotency-Key": "wallet-topup-refund-key1",
        },
        json={},
    )
    assert refund.status_code == 200, refund.text
    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert _wallet_uzs(wallet.json()) == Decimal("0")


async def test_topup_refund_refused_after_spend(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, user_id = await _login_user(integration_client, tg_id=908)
    payment = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-refund-spent",
    )
    await _settle_mock(integration_client, payment)

    user_wallet = await wallet_svc.ensure_account(
        db_session,
        owner_type="user",
        owner_id=user_id,
        kind="user_wallet",
        currency="UZS",
    )
    house = await wallet_svc.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_payments_received",
        currency="UZS",
    )
    await wallet_svc.post(
        db_session,
        kind="wallet_payment",
        legs=[
            Leg(account_id=user_wallet.id, direction="C", amount=Decimal("10000"), currency="UZS"),
            Leg(account_id=house.id, direction="D", amount=Decimal("10000"), currency="UZS"),
        ],
        idempotency_key="wallet-topup-test-spend-1",
    )
    await db_session.commit()

    admin, _ = await _login_user(integration_client, tg_id=909)
    await _grant_admin(db_session, tg_id=909)
    refund = await integration_client.post(
        f"/api/v1/admin/payments/{payment['id']}/refund",
        headers={
            "Authorization": f"Bearer {admin}",
            "Idempotency-Key": "wallet-topup-refund-spentk",
        },
        json={},
    )
    assert refund.status_code == 409

    leftover = (
        await db_session.execute(select(Order).where(Order.id == payment["order_id"]))
    ).scalar_one()
    assert leftover.purpose == "wallet_topup"


async def test_checkout_refuses_a_key_already_spent_on_a_deposit(
    integration_client: AsyncClient,
) -> None:
    """The guard `create_topup` has, in the other direction.

    Both live in `orders` and share one partial unique on
    ``(user_id, idempotency_key)``. `create_topup` checks the purpose of what
    it finds and answers 409; checkout replayed on the key alone, so a key
    already spent on a deposit would have handed the buyer that deposit back
    as though it were their purchase — no items, nothing bought.

    The SKU here is deliberately nonexistent: the replay short-circuit runs
    before any SKU is loaded, so reaching a SKU error at all would already
    mean the guard fired.
    """
    token, _ = await _login_user(integration_client, tg_id=910)
    await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-crosstalk-1",
    )
    order = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-topup-crosstalk-1",
        },
        json={
            "currency": "USD",
            "items": [{"sku_id": "00000000-0000-7000-8000-000000000000", "qty": 1}],
        },
    )
    assert order.status_code == 409, order.text
