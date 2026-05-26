"""Integration tests for the ``integrations`` module skeleton.

Covers:
- CRUD over ``sku_supplier_mapping`` via admin endpoints.
- Upsert is idempotent — second PUT updates, doesn't duplicate.
- ``game`` kind without ``external_variant_id`` → 422.
- Unknown SKU → 404.
- Non-admin → 403.
- ``sku_sourcing_rules`` still works untouched (no regression in decision).
- ``/admin/integrations/g2b/health`` reports the unconfigured state correctly.
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
from yupay.modules.integrations.models import SkuSupplierMapping
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
        slug="pubg",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG")],
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="PUBG UC")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-60uc",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


# ---------- mapping CRUD ----------


async def test_upsert_mapping_creates_row(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=401)
    await _grant_admin(db_session, tg_id=401)
    headers = {"Authorization": f"Bearer {admin}"}

    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
            "quantity": 1,
            "extra": {},
            "is_active": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sku_id"] == _seed_sku
    assert body["supplier_slug"] == "g2b"
    assert body["kind"] == "voucher"
    assert body["external_product_id"] == "42"
    assert body["quantity"] == 1
    assert body["is_active"] is True


async def test_upsert_is_idempotent(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=402)
    await _grant_admin(db_session, tg_id=402)
    headers = {"Authorization": f"Bearer {admin}"}
    url = f"/api/v1/admin/integrations/mappings/{_seed_sku}"
    payload = {
        "supplier_slug": "g2b",
        "kind": "voucher",
        "external_product_id": "42",
    }

    first = await integration_client.put(url, headers=headers, json=payload)
    assert first.status_code == 200

    payload2 = {**payload, "external_product_id": "99", "quantity": 5}
    second = await integration_client.put(url, headers=headers, json=payload2)
    assert second.status_code == 200
    assert second.json()["external_product_id"] == "99"
    assert second.json()["quantity"] == 5

    rows = list(
        (
            await db_session.execute(
                select(SkuSupplierMapping).where(SkuSupplierMapping.sku_id == _seed_sku)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_game_kind_requires_variant(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=403)
    await _grant_admin(db_session, tg_id=403)
    headers = {"Authorization": f"Bearer {admin}"}
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "game",
            "external_product_id": "pubg_mobile",
        },
    )
    assert r.status_code == 422, r.text


async def test_list_filters_by_supplier(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=404)
    await _grant_admin(db_session, tg_id=404)
    headers = {"Authorization": f"Bearer {admin}"}
    await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    r = await integration_client.get(
        "/api/v1/admin/integrations/mappings?supplier_slug=g2b",
        headers=headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(m["sku_id"] == _seed_sku for m in items)

    empty = await integration_client.get(
        "/api/v1/admin/integrations/mappings?supplier_slug=steam",
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []


async def test_delete_mapping(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=405)
    await _grant_admin(db_session, tg_id=405)
    headers = {"Authorization": f"Bearer {admin}"}
    await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    r = await integration_client.delete(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}/g2b",
        headers=headers,
    )
    assert r.status_code == 204

    again = await integration_client.delete(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}/g2b",
        headers=headers,
    )
    assert again.status_code == 404


async def test_upsert_unknown_sku_returns_404(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    admin = await _login_user(integration_client, tg_id=406)
    await _grant_admin(db_session, tg_id=406)
    fake_sku = new_id()
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{fake_sku}",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    assert r.status_code == 404, r.text


async def test_non_admin_forbidden(
    integration_client: AsyncClient,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=407)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers={"Authorization": f"Bearer {user}"},
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    assert r.status_code == 403


# ---------- health probe ----------


async def test_g2b_health_reports_unconfigured(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """With the test environment's empty ``G2B_API_KEY``, the stub probe
    must report ``available=false`` with a clear reason. The Sprint B
    adapter swaps this for the real /v1/getMe call."""
    admin = await _login_user(integration_client, tg_id=408)
    await _grant_admin(db_session, tg_id=408)
    r = await integration_client.get(
        "/api/v1/admin/integrations/g2b/health",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supplier"] == "g2b"
    assert body["available"] is False
    assert body["reason"]


async def test_unknown_supplier_health(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    admin = await _login_user(integration_client, tg_id=409)
    await _grant_admin(db_session, tg_id=409)
    r = await integration_client.get(
        "/api/v1/admin/integrations/wat/health",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert "unknown" in r.json()["reason"]


# ---------- sourcing regression ----------


async def test_sourcing_decision_untouched(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """Creating a supplier mapping must not silently change the sourcing
    decision — routing still comes from ``sku_sourcing_rules`` alone."""
    admin = await _login_user(integration_client, tg_id=410)
    await _grant_admin(db_session, tg_id=410)
    headers = {"Authorization": f"Bearer {admin}"}
    await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    decision = await integration_client.get(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}", headers=headers
    )
    assert decision.status_code == 200
    # Default decision is unchanged — inventory-first with mock fallback.
    assert decision.json()["primary"] == "inventory"
    assert decision.json()["fallback"] == "supplier:mock"
    assert decision.json()["rule_present"] is False
