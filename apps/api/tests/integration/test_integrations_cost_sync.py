"""Tests for the on-save ``cost_usdt`` refresh.

Saving a mapping pulls the upstream price from G2B (or the cached
catalog row for vouchers) and writes it into ``Sku.cost_usdt``. The
mutation is reported back through the ``cost_sync`` block of the
response so the admin UI can flash the change.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
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
from yupay.modules.integrations.service import upsert_catalog_entry
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
G2B_BASE = "https://g2b.test/v1"


@pytest.fixture(autouse=True)
def _g2b_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_admin(client: AsyncClient, db: AsyncSession, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return token


async def _seed_sku(db: AsyncSession, kind: str) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{kind}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"br-{kind}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Br")],
    )
    product = Product(
        id=new_id(),
        slug=f"prod-{kind}",
        brand_id=brand.id,
        kind=kind,
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{kind}",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _seed_priced_sku(
    db: AsyncSession, slug_suffix: str, *, cost_usdt: str, price_usd: str, margin_percent: str
) -> str:
    """Like ``_seed_sku`` but with a cost basis and a saved margin, for the
    ratchet tests: a mapping save is the one caller of
    ``set_sku_cost_usdt`` that still passes ``allow_price_drop=True``."""
    category = Category(
        id=new_id(),
        slug=f"cat-{slug_suffix}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"br-{slug_suffix}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Br")],
    )
    product = Product(
        id=new_id(),
        slug=f"prod-{slug_suffix}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{slug_suffix}",
        denomination="60",
        region="WW",
        price_usd=Decimal(price_usd),
        cost_usdt=Decimal(cost_usdt),
        margin_percent=Decimal(margin_percent),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


# ---------- voucher branch ----------


async def test_cost_sync_voucher_uses_cache_unit_price(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, kind="voucher")
    await upsert_catalog_entry(
        db_session,
        supplier_slug="g2b",
        kind="voucher",
        external_id="42",
        title="PSN $10",
        raw={"id": 42, "title": "PSN $10", "unit_price": 9.05},
    )
    await db_session.commit()

    admin = await _login_admin(integration_client, db_session, tg_id=801)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{sku_id}",
        headers={"Authorization": f"Bearer {admin}"},
        json={"supplier_slug": "g2b", "kind": "voucher", "external_product_id": "42"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cost_sync"]["updated"] is True
    assert body["cost_sync"]["new_cost"] == "9.05"
    assert body["cost_sync"]["source"] == "supplier_catalog_cache.unit_price"

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("9.05")


async def test_cost_sync_voucher_reports_cache_miss(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, kind="voucher")
    admin = await _login_admin(integration_client, db_session, tg_id=802)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{sku_id}",
        headers={"Authorization": f"Bearer {admin}"},
        json={"supplier_slug": "g2b", "kind": "voucher", "external_product_id": "9999"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cost_sync"]["updated"] is False
    assert "кэше" in (body["cost_sync"]["reason"] or "")


# ---------- game branch ----------


@respx.mock
async def test_cost_sync_game_pulls_denom_amount_from_g2b(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, kind="top_up")
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={
                "catalogues": [
                    {"id": 264, "name": "60", "amount": 0.89},
                    {"id": 258, "name": "660", "amount": 8.85},
                ],
                "success": True,
            },
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=803)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{sku_id}",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "supplier_slug": "g2b",
            "kind": "game",
            "external_product_id": "pubgm",
            "external_variant_id": "60",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cost_sync"]["updated"] is True
    assert body["cost_sync"]["new_cost"] == "0.89"

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.89")


@respx.mock
async def test_cost_sync_game_unknown_denom_reports_reason(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, kind="top_up")
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 264, "name": "60", "amount": 0.89}]},
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=804)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{sku_id}",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "supplier_slug": "g2b",
            "kind": "game",
            "external_product_id": "pubgm",
            "external_variant_id": "9001 UC",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cost_sync"]["updated"] is False
    assert "9001" in (body["cost_sync"]["reason"] or "")


# ---------- allow_price_drop — the mapping-save route is "the admin path" ----------


@respx.mock
async def test_mapping_save_still_lowers_price_on_a_cost_drop(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The mapping-save route calls ``refresh_sku_cost_for_mapping`` with
    ``allow_price_drop=True`` — an operator choosing this mapping in the
    admin UI may still lower a SKU's price. This is the "admin path"
    Task 2 exempts from the hourly ratchet: unlike the automatic refresh,
    this call site must keep lowering the price on a cost drop, exactly
    as it did before ``allow_price_drop`` existed."""
    sku_id = await _seed_priced_sku(
        db_session, "admin-drop", cost_usdt="10.00", price_usd="12.00", margin_percent="20"
    )
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 264, "name": "60", "amount": 8.00}]},
        )
    )
    admin = await _login_admin(integration_client, db_session, tg_id=805)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{sku_id}",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "supplier_slug": "g2b",
            "kind": "game",
            "external_product_id": "pubgm",
            "external_variant_id": "60",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cost_sync"]["updated"] is True
    assert body["cost_sync"]["new_cost"] == "8.0"

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("8.00")
    assert sku.price_usd == Decimal("9.60"), "20% margin on the new $8 cost — the price must drop"
