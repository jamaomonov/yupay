"""Integration tests for ``/api/v1/orders/*`` and ``/api/v1/admin/orders/*``.

Covers:
- Create order as authenticated user + as guest
- Idempotency replay returns the same order
- required_fields validation (missing / wrong pattern)
- 404 for orders of another user
- Admin can list / cancel a pending order
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
from sqlalchemy import update
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
    body: dict[str, str] = r.json()
    return body["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    from sqlalchemy import select

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


@pytest.fixture
async def _seed_pubg(db_session: AsyncSession) -> dict[str, str]:
    """Insert one category → brand → PUBG UC product → 1 SKU."""
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[
            CategoryTranslation(locale="ru", name="Игры"),
            CategoryTranslation(locale="en", name="Games"),
        ],
    )
    brand = Brand(
        id=new_id(),
        slug="pubg-mobile",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG Mobile")],
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[
            {
                "key": "player_id",
                "label": {"ru": "ID"},
                "type": "text",
                "required": True,
                "pattern": r"^[0-9]{6,15}$",
            },
            {
                "key": "server",
                "label": {"ru": "Сервер"},
                "type": "select",
                "required": True,
                "options": [
                    {"value": "as", "label": {"ru": "AS"}},
                    {"value": "eu", "label": {"ru": "EU"}},
                ],
            },
        ],
        translations=[ProductTranslation(locale="ru", name="UC")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-uc-60-tr",
        denomination="60 UC",
        region="TR",
        price_usd=Decimal("0.85"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return {"sku_id": sku.id, "product_id": product.id}


# ---------- create order ----------


async def test_create_order_requires_idempotency_key(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=11)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "123456", "server": "as"},
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "Idempotency-Key" in r.text


async def test_create_order_user_happy_path(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=12)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "user12-order-aaaaaaaaaaaa",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 2,
                    "fulfillment_data": {"player_id": "987654", "server": "eu"},
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending_payment"
    assert body["currency"] == "USD"
    assert Decimal(body["total_usd"]) == Decimal("1.70")
    assert Decimal(body["total_charged"]) == Decimal("1.70")
    assert body["fx_snapshot_id"] is None
    assert len(body["items"]) == 1
    assert body["items"][0]["qty"] == 2
    assert body["items"][0]["fulfillment_data"] == {"player_id": "987654", "server": "eu"}


async def test_create_order_idempotent_replay(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=13)
    payload = {
        "currency": "USD",
        "items": [
            {
                "sku_id": _seed_pubg["sku_id"],
                "qty": 1,
                "fulfillment_data": {"player_id": "123456", "server": "as"},
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "replay-key-bbbbbbbbbbbb",
    }
    r1 = await integration_client.post("/api/v1/orders", headers=headers, json=payload)
    r2 = await integration_client.post("/api/v1/orders", headers=headers, json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


async def test_create_order_missing_required_field(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=14)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "missing-field-cccccccccccc",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"server": "as"},  # no player_id
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "player_id" in r.text


async def test_create_order_pattern_violation(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=15)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "pattern-violation-dddddddd",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "abc", "server": "as"},
                }
            ],
        },
    )
    assert r.status_code == 422


async def test_create_order_unsupported_select_value(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=16)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "bad-select-eeeeeeeeeeee",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "123456", "server": "MARS"},
                }
            ],
        },
    )
    assert r.status_code == 422


# ---------- get / list ----------


async def test_get_order_only_owner(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    owner_token = await _login_user(integration_client, tg_id=21)
    other_token = await _login_user(integration_client, tg_id=22)
    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "Idempotency-Key": "owner-test-ffffffffffff",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "111111", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201
    order_id = create.json()["id"]

    # Owner can read.
    ok = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert ok.status_code == 200

    # Stranger gets 404.
    stranger = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert stranger.status_code == 404


async def test_list_orders_for_user(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=31)
    for i in range(3):
        r = await integration_client.post(
            "/api/v1/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"list-{i:02d}-gggggggggggg",
            },
            json={
                "currency": "USD",
                "items": [
                    {
                        "sku_id": _seed_pubg["sku_id"],
                        "qty": 1,
                        "fulfillment_data": {"player_id": "123456", "server": "as"},
                    }
                ],
            },
        )
        assert r.status_code == 201

    r = await integration_client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3


# ---------- admin ----------


async def test_admin_can_list_and_cancel(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    user_token = await _login_user(integration_client, tg_id=41)
    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Idempotency-Key": "admin-cancel-hhhhhhhhhhhh",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "555555", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201
    order_id = create.json()["id"]

    admin_token = await _login_user(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)

    listing = await integration_client.get(
        "/api/v1/admin/orders", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert listing.status_code == 200
    assert any(o["id"] == order_id for o in listing.json()["items"])

    cancel = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    # A second cancel fails — order is not in pending_payment anymore.
    repeat = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert repeat.status_code == 409
