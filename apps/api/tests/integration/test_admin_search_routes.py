"""Integration tests for the cross-entity admin search endpoint.

Covers:
- auth gate (401/403)
- response shape (grouped hits per source)
- per-source matching (user/order/payment/sku)
- query validation & limit clamping
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio


BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int = 100500) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    body: dict[str, str] = r.json()
    return body["access_token"]


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    from sqlalchemy import select

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    return {"Authorization": f"Bearer {token}"}


# ---------- auth gate ----------


async def test_search_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/search", params={"q": "alice"})
    assert r.status_code == 401


async def test_search_forbids_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=999)
    r = await integration_client.get(
        "/api/v1/admin/search",
        params={"q": "alice"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- response shape ----------


async def test_empty_db_returns_all_groups(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "nothing"}, headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"users", "orders", "payments", "skus"}
    for group in body.values():
        assert group == []


async def test_query_too_short_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "a"}, headers=_admin_headers
    )
    assert r.status_code == 422


# ---------- per-source matching ----------


async def _make_user(
    db: AsyncSession,
    *,
    email: str | None,
    display_name: str | None = None,
    tg_user_id: int | None = None,
    tg_username: str | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id,
            email=email,
            display_name=display_name,
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()
    if tg_user_id is not None:
        db.add(
            TelegramLink(
                id=str(uuid.uuid4()),
                user_id=user_id,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
            )
        )
    await db.commit()
    return user_id


async def _make_order(db: AsyncSession, *, user_id: str | None = None) -> str:
    from datetime import datetime, timedelta

    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None if user_id else "guest@example.com",
            status="pending_payment",
            currency="USD",
            total_usd=Decimal("10.00"),
            total_charged=Decimal("10.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()
    return order_id


async def _make_payment(db: AsyncSession, *, order_id: str, external_id: str | None) -> str:
    payment_id = str(uuid.uuid4())
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="stub",
            status="pending",
            amount=Decimal("10.00"),
            currency="USD",
            external_id=external_id,
        )
    )
    await db.commit()
    return payment_id


async def _make_sku(db: AsyncSession, *, sku_code: str) -> str:
    cat_id = str(uuid.uuid4())
    brand_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    sku_id = str(uuid.uuid4())
    db.add(Category(id=cat_id, slug=f"cat-{sku_code}"))
    await db.flush()
    db.add(Brand(id=brand_id, slug=f"brand-{sku_code}", category_id=cat_id))
    await db.flush()
    db.add(
        Product(
            id=product_id,
            slug=f"prod-{sku_code}",
            brand_id=brand_id,
            kind="top_up",
        )
    )
    await db.flush()
    db.add(
        Sku(
            id=sku_id,
            product_id=product_id,
            sku_code=sku_code,
            price_usd=Decimal("1.00"),
        )
    )
    await db.commit()
    return sku_id


async def test_finds_user_by_email_case_insensitive(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email="Alice@Example.COM", display_name="Alice")
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "alice@"}, headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [h["id"] for h in body["users"]]
    assert user_id in ids
    hit = next(h for h in body["users"] if h["id"] == user_id)
    assert hit["type"] == "user"
    assert hit["path"] == f"/customers/{user_id}"


async def test_finds_user_by_telegram_username(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email=None, tg_user_id=555111, tg_username="bobby")
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "bobby"}, headers=_admin_headers
    )
    assert r.status_code == 200
    assert any(h["id"] == user_id for h in r.json()["users"])


async def test_finds_user_by_numeric_tg_id(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email=None, tg_user_id=987654321, tg_username=None)
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "987654321"}, headers=_admin_headers
    )
    assert r.status_code == 200
    assert any(h["id"] == user_id for h in r.json()["users"])


async def test_finds_order_by_uuid_prefix(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email="orderer@example.com")
    order_id = await _make_order(db_session, user_id=user_id)
    prefix = order_id[:8]
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": prefix}, headers=_admin_headers
    )
    assert r.status_code == 200
    assert any(h["id"] == order_id for h in r.json()["orders"])


async def test_finds_payment_by_external_id(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email="payer@example.com")
    order_id = await _make_order(db_session, user_id=user_id)
    payment_id = await _make_payment(db_session, order_id=order_id, external_id="EXT-PAY-12345")
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "ext-pay-123"}, headers=_admin_headers
    )
    assert r.status_code == 200
    assert any(h["id"] == payment_id for h in r.json()["payments"])


async def test_finds_sku_by_code(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    sku_id = await _make_sku(db_session, sku_code="PUBG-60-TR")
    r = await integration_client.get(
        "/api/v1/admin/search", params={"q": "pubg-60"}, headers=_admin_headers
    )
    assert r.status_code == 200
    assert any(h["id"] == sku_id for h in r.json()["skus"])


async def test_limit_is_clamped(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    # 15 users, ask for limit=5, expect at most 5 per group
    for i in range(15):
        await _make_user(db_session, email=f"sameprefix{i}@example.com")
    r = await integration_client.get(
        "/api/v1/admin/search",
        params={"q": "sameprefix", "limit": 5},
        headers=_admin_headers,
    )
    assert r.status_code == 200
    assert len(r.json()["users"]) == 5
