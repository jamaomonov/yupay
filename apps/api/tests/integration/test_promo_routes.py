"""Promo codes: admin issuance and customer redemption.

A code is a fixed-denomination gift that credits the customer's ``user_wallet``
(``D user_wallet / C house_promo_expense``) — immediately visible in the
balance and spendable through the wallet gateway. One redemption per user,
optional global cap and expiry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
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
from yupay.modules.users.models import TelegramLink, User

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


async def _admin_token(client: AsyncClient, db: AsyncSession, tg_id: int) -> str:
    token = await _login_user(client, tg_id)
    await _grant_admin(db, tg_id)
    return token


async def _create_code(
    client: AsyncClient,
    *,
    admin: str,
    code: str,
    amount: str = "5.00",
    currency: str = "USD",
    **extra: object,
) -> dict[str, object]:
    r = await client.post(
        "/api/v1/admin/promo",
        headers={"Authorization": f"Bearer {admin}", "Idempotency-Key": f"pc-{code}-padpadpad"},
        json={"code": code, "amount": amount, "currency": currency, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _redeem(client: AsyncClient, *, token: str, code: str, key: str):
    return await client.post(
        "/api/v1/promo/redeem",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"code": code},
    )


async def _usd_balance(client: AsyncClient, token: str) -> Decimal:
    r = await client.get("/api/v1/wallet", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    for b in r.json()["balances"]:
        if b["currency"] == "USD" and b["kind"] == "user_wallet":
            return Decimal(b["balance"])
    return Decimal("0")


# ---------- redemption ----------


async def test_redeem_credits_wallet(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1001)
    await _create_code(integration_client, admin=admin, code="WELCOME5")

    token = await _login_user(integration_client, tg_id=1002)
    r = await _redeem(integration_client, token=token, code="welcome5", key="pr-1002-padpadpadpad")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "WELCOME5"
    assert Decimal(body["amount"]) == Decimal("5.00")
    assert body["currency"] == "USD"

    assert await _usd_balance(integration_client, token) == Decimal("5.00")


async def test_redeem_requires_auth_and_key(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/promo/redeem",
        headers={"Idempotency-Key": "pr-anon-padpadpadpad"},
        json={"code": "X"},
    )
    assert r.status_code == 401, r.text

    token = await _login_user(integration_client, tg_id=1003)
    r = await integration_client.post(
        "/api/v1/promo/redeem", headers={"Authorization": f"Bearer {token}"}, json={"code": "X"}
    )
    assert r.status_code == 422, r.text


async def test_redeem_unknown_code_is_404(integration_client: AsyncClient) -> None:
    token = await _login_user(integration_client, tg_id=1004)
    r = await _redeem(integration_client, token=token, code="NOPE", key="pr-1004-padpadpadpad")
    assert r.status_code == 404, r.text


async def test_redeem_twice_conflicts_but_replays_with_same_key(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1005)
    await _create_code(integration_client, admin=admin, code="ONCE5")
    token = await _login_user(integration_client, tg_id=1006)

    first = await _redeem(integration_client, token=token, code="ONCE5", key="pr-1006-padpadpadpad")
    assert first.status_code == 200, first.text

    # Same Idempotency-Key → replay of the original success.
    replay = await _redeem(
        integration_client, token=token, code="ONCE5", key="pr-1006-padpadpadpad"
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    # A NEW attempt is a genuine second redemption → refused.
    again = await _redeem(integration_client, token=token, code="ONCE5", key="pr-1006b-padpadpad")
    assert again.status_code == 409, again.text
    # The client branches on ``code``, not on the English detail.
    assert again.json()["code"] == "already_redeemed"

    # Balance credited exactly once.
    assert await _usd_balance(integration_client, token) == Decimal("5.00")


async def test_redeem_respects_global_cap(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1007)
    await _create_code(integration_client, admin=admin, code="CAP1", max_redemptions=1)

    first_user = await _login_user(integration_client, tg_id=1008)
    r = await _redeem(integration_client, token=first_user, code="CAP1", key="pr-1008-padpadpadpad")
    assert r.status_code == 200, r.text

    second_user = await _login_user(integration_client, tg_id=1009)
    r = await _redeem(
        integration_client, token=second_user, code="CAP1", key="pr-1009-padpadpadpad"
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "exhausted"


async def test_redeem_expired_and_deactivated_conflict(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1010)
    past = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    await _create_code(integration_client, admin=admin, code="OLD5", expires_at=past)
    created = await _create_code(integration_client, admin=admin, code="DEAD5")

    token = await _login_user(integration_client, tg_id=1011)
    r = await _redeem(integration_client, token=token, code="OLD5", key="pr-1011a-padpadpad")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "expired"

    r = await integration_client.post(
        f"/api/v1/admin/promo/{created['id']}/deactivate",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    r = await _redeem(integration_client, token=token, code="DEAD5", key="pr-1011b-padpadpad")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "inactive"


# ---------- the credited money is real: spend it ----------


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="dota",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Dota 2")],
    )
    product = Product(
        id=new_id(),
        slug="dota-points",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Dota Points")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="dota-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def test_promo_money_pays_for_an_order(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1012)
    await _create_code(integration_client, admin=admin, code="PAY5")

    token = await _login_user(integration_client, tg_id=1013)
    r = await _redeem(integration_client, token=token, code="PAY5", key="pr-1013-padpadpadpad")
    assert r.status_code == 200, r.text

    order = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "pr-order-1013-pad"},
        json={
            "currency": "USD",
            "items": [{"sku_id": _seed_sku, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert order.status_code == 201, order.text

    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "pr-intent-1013-pad"},
        json={"order_id": order.json()["id"], "provider": "wallet"},
    )
    assert intent.status_code == 201, intent.text
    assert intent.json()["status"] == "succeeded"
    assert await _usd_balance(integration_client, token) == Decimal("3.50")


# ---------- admin surface ----------


async def test_admin_list_shows_usage(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1014)
    await _create_code(integration_client, admin=admin, code="LIST5", max_redemptions=10)
    token = await _login_user(integration_client, tg_id=1015)
    await _redeem(integration_client, token=token, code="LIST5", key="pr-1015-padpadpadpad")

    r = await integration_client.get(
        "/api/v1/admin/promo", headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.status_code == 200, r.text
    row = next(p for p in r.json()["items"] if p["code"] == "LIST5")
    assert row["redemptions"] == 1
    assert row["max_redemptions"] == 10
    assert row["active"] is True


async def test_admin_create_requires_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_user(integration_client, tg_id=1016)
    r = await integration_client.post(
        "/api/v1/admin/promo",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "pc-noadmin-padpad"},
        json={"code": "HAX", "amount": "5.00", "currency": "USD"},
    )
    assert r.status_code == 403, r.text


async def test_admin_duplicate_code_conflicts(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session, tg_id=1017)
    await _create_code(integration_client, admin=admin, code="DUP5")
    r = await integration_client.post(
        "/api/v1/admin/promo",
        headers={"Authorization": f"Bearer {admin}", "Idempotency-Key": "pc-dup2-padpadpadpad"},
        json={"code": "dup5", "amount": "1.00", "currency": "USD"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "duplicate_code"
