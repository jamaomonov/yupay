"""Integration tests for the wallet skeleton.

Covers:
- ``GET /wallet`` reports only the three user-visible kinds, in account currency
- ``GET /wallet/transactions`` shows balanced legs
- ``POST /admin/wallet/adjust`` credits and claws back; idempotent on key
- ``GET /admin/wallet/{user_id}`` returns all accounts + recent history
- Ledger invariant rejects unbalanced legs
- Non-admin gets 403 from admin routes
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
from yupay.core.errors import ValidationError
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


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return user_id


async def _user_id_for_tg(db: AsyncSession, tg_id: int) -> str:
    return (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()


# ---------- customer ----------


async def test_empty_wallet_returns_no_balances(
    integration_client: AsyncClient,
) -> None:
    token = await _login_user(integration_client, tg_id=501)
    r = await integration_client.get("/api/v1/wallet", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"balances": []}


async def test_admin_credit_appears_on_user_wallet(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_token = await _login_user(integration_client, tg_id=502)
    user_id = await _user_id_for_tg(db_session, 502)

    admin_token = await _login_user(integration_client, tg_id=503)
    await _grant_admin(db_session, tg_id=503)

    r = await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "user_id": user_id,
            "kind": "user_cashback",
            "currency": "USD",
            "amount": "5.000000",
            "reason": "testing",
            "idempotency_key": "adj-credit-aaaaaaaa-001",
        },
    )
    assert r.status_code == 200, r.text
    txn = r.json()
    assert txn["kind"] == "admin.adjust"
    assert len(txn["postings"]) == 2

    overview = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert overview.status_code == 200
    body = overview.json()
    assert len(body["balances"]) == 1
    assert body["balances"][0]["kind"] == "user_cashback"
    assert Decimal(body["balances"][0]["balance"]) == Decimal("5")


async def test_admin_clawback_decreases_balance(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_token = await _login_user(integration_client, tg_id=504)
    user_id = await _user_id_for_tg(db_session, 504)
    admin_token = await _login_user(integration_client, tg_id=505)
    await _grant_admin(db_session, tg_id=505)

    headers = {"Authorization": f"Bearer {admin_token}"}
    credit = await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers=headers,
        json={
            "user_id": user_id,
            "kind": "user_promo_credit",
            "currency": "USD",
            "amount": "10",
            "reason": "promo seed",
            "idempotency_key": "adj-claw-aaaaaaaa-001",
        },
    )
    assert credit.status_code == 200
    claw = await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers=headers,
        json={
            "user_id": user_id,
            "kind": "user_promo_credit",
            "currency": "USD",
            "amount": "-3",
            "reason": "promo retraction",
            "idempotency_key": "adj-claw-aaaaaaaa-002",
        },
    )
    assert claw.status_code == 200

    overview = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert overview.status_code == 200
    bal = next(b for b in overview.json()["balances"] if b["kind"] == "user_promo_credit")
    assert Decimal(bal["balance"]) == Decimal("7")


async def test_idempotent_replay_returns_same_transaction(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await _user_id_for_tg(
        db_session, (await _grant_user_and_login(integration_client, db_session, 506))
    )
    admin_token = await _login_user(integration_client, tg_id=507)
    await _grant_admin(db_session, tg_id=507)
    body = {
        "user_id": user_id,
        "kind": "user_wallet",
        "currency": "USD",
        "amount": "2",
        "reason": "manual replay",
        "idempotency_key": "adj-replay-bbbbbbbbb-001",
    }
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = await integration_client.post("/api/v1/admin/wallet/adjust", headers=headers, json=body)
    second = await integration_client.post(
        "/api/v1/admin/wallet/adjust", headers=headers, json=body
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


async def _grant_user_and_login(client: AsyncClient, db: AsyncSession, tg_id: int) -> int:
    await _login_user(client, tg_id=tg_id)
    return tg_id


async def test_my_transactions_lists_recent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_token = await _login_user(integration_client, tg_id=508)
    user_id = await _user_id_for_tg(db_session, 508)
    admin_token = await _login_user(integration_client, tg_id=509)
    await _grant_admin(db_session, tg_id=509)

    headers = {"Authorization": f"Bearer {admin_token}"}
    for i in range(3):
        r = await integration_client.post(
            "/api/v1/admin/wallet/adjust",
            headers=headers,
            json={
                "user_id": user_id,
                "kind": "user_wallet",
                "currency": "USD",
                "amount": "1",
                "reason": f"seed-{i}",
                "idempotency_key": f"adj-list-cccccccc-{i:03d}",
            },
        )
        assert r.status_code == 200

    r = await integration_client.get(
        "/api/v1/wallet/transactions",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3
    for txn in r.json()["items"]:
        sums = {"D": Decimal("0"), "C": Decimal("0")}
        for leg in txn["postings"]:
            sums[leg["direction"]] += Decimal(leg["amount"])
        assert sums["D"] == sums["C"]


# ---------- admin view ----------


async def test_admin_user_ledger(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_user(integration_client, tg_id=510)
    user_id = await _user_id_for_tg(db_session, 510)
    admin_token = await _login_user(integration_client, tg_id=511)
    await _grant_admin(db_session, tg_id=511)

    headers = {"Authorization": f"Bearer {admin_token}"}
    await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers=headers,
        json={
            "user_id": user_id,
            "kind": "user_wallet",
            "currency": "USD",
            "amount": "12.50",
            "reason": "starter",
            "idempotency_key": "adj-view-dddddddddd-001",
        },
    )
    r = await integration_client.get(f"/api/v1/admin/wallet/{user_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == user_id
    wallet = next(a for a in body["accounts"] if a["kind"] == "user_wallet")
    assert Decimal(wallet["balance"]) == Decimal("12.50")
    assert body["recent_transactions"]


async def test_admin_required(integration_client: AsyncClient) -> None:
    token = await _login_user(integration_client, tg_id=520)
    r = await integration_client.get(
        f"/api/v1/admin/wallet/{token}", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


# ---------- /admin/wallet/adjustments (UC4 "Мои корректировки") ----------


async def test_recent_adjustments_filters_to_me(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Customer that both admins will adjust.
    customer_id = await _user_id_for_tg(
        db_session, (await _grant_user_and_login(integration_client, db_session, 530))
    )

    admin_a_token = await _login_user(integration_client, tg_id=531)
    admin_a_id = await _grant_admin(db_session, tg_id=531)
    admin_b_token = await _login_user(integration_client, tg_id=532)
    await _grant_admin(db_session, tg_id=532)

    await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers={"Authorization": f"Bearer {admin_a_token}"},
        json={
            "user_id": customer_id,
            "kind": "user_cashback",
            "currency": "USD",
            "amount": "1",
            "reason": "by A",
            "idempotency_key": "rec-feed-aaaaaa-001",
        },
    )
    await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers={"Authorization": f"Bearer {admin_b_token}"},
        json={
            "user_id": customer_id,
            "kind": "user_cashback",
            "currency": "USD",
            "amount": "2",
            "reason": "by B",
            "idempotency_key": "rec-feed-bbbbbb-001",
        },
    )

    # admin A asks for "mine" — sees only its own row.
    mine = await integration_client.get(
        "/api/v1/admin/wallet/adjustments?actor=me",
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert mine.status_code == 200
    items = mine.json()["items"]
    assert all(t["actor"] == f"admin:{admin_a_id}" for t in items)
    assert any(t["extra_metadata"]["reason"] == "by A" for t in items)
    assert not any(t["extra_metadata"]["reason"] == "by B" for t in items)


async def test_recent_adjustments_all_actor(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    customer_id = await _user_id_for_tg(
        db_session, (await _grant_user_and_login(integration_client, db_session, 540))
    )

    admin_a_token = await _login_user(integration_client, tg_id=541)
    await _grant_admin(db_session, tg_id=541)
    admin_b_token = await _login_user(integration_client, tg_id=542)
    await _grant_admin(db_session, tg_id=542)

    for token, key, reason in (
        (admin_a_token, "rec-all-aaaaaa-001", "by A"),
        (admin_b_token, "rec-all-bbbbbb-001", "by B"),
    ):
        await integration_client.post(
            "/api/v1/admin/wallet/adjust",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": customer_id,
                "kind": "user_wallet",
                "currency": "USD",
                "amount": "1",
                "reason": reason,
                "idempotency_key": key,
            },
        )

    out = await integration_client.get(
        "/api/v1/admin/wallet/adjustments?actor=all",
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert out.status_code == 200
    reasons = {t["extra_metadata"]["reason"] for t in out.json()["items"]}
    assert {"by A", "by B"}.issubset(reasons)


async def test_recent_adjustments_bad_actor_400(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_user(integration_client, tg_id=551)
    await _grant_admin(db_session, tg_id=551)
    r = await integration_client.get(
        "/api/v1/admin/wallet/adjustments?actor=someone",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


# ---------- service-level invariants ----------


async def test_service_rejects_unbalanced_legs(db_session: AsyncSession) -> None:
    acc_user = await wallet_svc.ensure_account(
        db_session,
        owner_type="user",
        owner_id="00000000-0000-7000-8000-000000000fff",
        kind="user_wallet",
        currency="USD",
    )
    acc_house = await wallet_svc.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_promo_expense",
        currency="USD",
    )
    with pytest.raises(ValidationError, match="SUM"):
        await wallet_svc.post(
            db_session,
            kind="manual.test",
            legs=[
                Leg(account_id=acc_user.id, direction="D", amount=Decimal("5"), currency="USD"),
                Leg(account_id=acc_house.id, direction="C", amount=Decimal("4"), currency="USD"),
            ],
            idempotency_key="bad-invariant-eeeeeeee-001",
        )


async def test_service_balance_respects_normal_side(
    db_session: AsyncSession,
) -> None:
    acc_user = await wallet_svc.ensure_account(
        db_session,
        owner_type="user",
        owner_id="00000000-0000-7000-8000-00000000aaaa",
        kind="user_wallet",
        currency="USD",
    )
    acc_revenue = await wallet_svc.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_revenue",
        currency="USD",
    )
    await wallet_svc.post(
        db_session,
        kind="manual.normal_side",
        legs=[
            Leg(account_id=acc_user.id, direction="D", amount=Decimal("3"), currency="USD"),
            Leg(account_id=acc_revenue.id, direction="C", amount=Decimal("3"), currency="USD"),
        ],
        idempotency_key="normal-side-ffffffff-001",
    )
    assert await wallet_svc.balance(db_session, acc_user.id) == Decimal("3")
    assert await wallet_svc.balance(db_session, acc_revenue.id) == Decimal("3")
