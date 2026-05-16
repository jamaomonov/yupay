"""Integration tests for ``/api/v1/admin/catalog/*`` write endpoints.

Covers:
- 401 without a token, 403 with a non-admin token, 200 with admin
- CRUD round-trip for category → brand → product → SKU
- Validation: slug pattern, duplicate slug → 409
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
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
    token: str = body["access_token"]
    return token


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    """Promote the just-logged-in user to admin via direct DB update."""
    from sqlalchemy import select

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(
        update(User).where(User.id == user_id).values(roles=["admin"])
    )
    await db_session.commit()


# ---------- auth guard ----------


async def test_admin_endpoint_401_without_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/catalog/brands")
    assert r.status_code == 401


async def test_admin_endpoint_403_for_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=200)
    r = await integration_client.get(
        "/api/v1/admin/catalog/brands",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- CRUD round-trip ----------


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    # Mint a fresh token so the user's role is re-read on next request (it is — current_user
    # always hits the DB). One token is enough.
    return {"Authorization": f"Bearer {token}"}


async def test_full_crud_flow(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    # 1) Category
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={
            "slug": "test-cat",
            "icon": "gamepad",
            "sort_order": 100,
            "active": True,
            "translations": [
                {"locale": "ru", "name": "Тест"},
                {"locale": "en", "name": "Test"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    category = r.json()
    category_id = category["id"]
    assert category["slug"] == "test-cat"

    # 2) Brand
    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=_admin_headers,
        json={
            "slug": "test-brand",
            "category_id": category_id,
            "accent_color": "#FF0000",
            "translations": [{"locale": "ru", "name": "Тестбренд"}],
        },
    )
    assert r.status_code == 201, r.text
    brand_id = r.json()["id"]

    # 3) Product (with required_fields)
    r = await integration_client.post(
        "/api/v1/admin/catalog/products",
        headers=_admin_headers,
        json={
            "slug": "test-product",
            "brand_id": brand_id,
            "kind": "top_up",
            "supplier_hint": "codashop",
            "required_fields": [
                {
                    "key": "player_id",
                    "label": {"ru": "ID", "en": "ID"},
                    "type": "text",
                    "required": True,
                },
            ],
            "translations": [{"locale": "ru", "name": "Продукт"}],
        },
    )
    assert r.status_code == 201, r.text
    product = r.json()
    product_id = product["id"]
    assert product["required_fields"][0]["key"] == "player_id"

    # 4) SKU with an override
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "test-sku-1",
            "denomination": "1 unit",
            "region": "TR",
            "price_usd": "1.50",
            "price_overrides": [{"currency": "rub", "price": "150.00"}],
        },
    )
    assert r.status_code == 201, r.text
    sku = r.json()
    sku_id = sku["id"]
    assert sku["price_overrides"][0]["currency"] == "RUB"  # uppercased by validator

    # 5) PATCH product
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/products/{product_id}",
        headers=_admin_headers,
        json={"active": False, "sort_order": 999},
    )
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["sort_order"] == 999

    # 6) Listing returns the inactive product (admin sees everything)
    r = await integration_client.get(
        "/api/v1/admin/catalog/products", headers=_admin_headers
    )
    assert r.status_code == 200
    assert any(p["id"] == product_id for p in r.json())

    # 7) Delete cascade: deleting the product removes its SKUs
    r = await integration_client.delete(
        f"/api/v1/admin/catalog/products/{product_id}", headers=_admin_headers
    )
    assert r.status_code == 204
    r = await integration_client.get(
        f"/api/v1/admin/catalog/skus/{sku_id}", headers=_admin_headers
    )
    # The SKU endpoint isn't defined for GET-by-id — but the product DELETE cascade
    # should have removed it. Verify via the list endpoint.
    r = await integration_client.get(
        "/api/v1/admin/catalog/skus", headers=_admin_headers
    )
    assert all(s["id"] != sku_id for s in r.json())


async def test_duplicate_slug_returns_409(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    payload = {
        "slug": "dup-cat",
        "translations": [{"locale": "ru", "name": "X"}],
    }
    r1 = await integration_client.post(
        "/api/v1/admin/catalog/categories", headers=_admin_headers, json=payload
    )
    assert r1.status_code == 201
    r2 = await integration_client.post(
        "/api/v1/admin/catalog/categories", headers=_admin_headers, json=payload
    )
    assert r2.status_code == 409


async def test_invalid_slug_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={
            "slug": "Bad Slug With Spaces!",  # fails the pattern
            "translations": [{"locale": "ru", "name": "X"}],
        },
    )
    assert r.status_code == 422
