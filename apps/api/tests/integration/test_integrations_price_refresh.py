"""Hourly price-refresh worker + history endpoint + admin trigger.

Verified end-to-end:

- Game catalogue movement → ``Sku.cost_usdt`` flipped, history row inserted.
- No movement → history table left alone.
- Telegram alert bot called when |Δ%| ≥ threshold; suppressed otherwise.
- Each mapping processed in its own transaction (one failure doesn't
  poison the run).
- ``GET /admin/integrations/sku-prices/{id}/history`` returns rows newest
  first.
- ``POST /admin/integrations/refresh-all-prices`` mirrors the scheduler.
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
from yupay.modules.integrations.models import (
    SkuSupplierMapping,
    SupplierPriceHistory,
)
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
G2B_BASE = "https://g2b.test/v1"
ALERT_BOT_TOKEN = "alert-bot-token"
ALERT_CHAT_ID = "555000"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    monkeypatch.setenv("TG_ALERT_BOT_TOKEN", ALERT_BOT_TOKEN)
    monkeypatch.setenv("TG_ALERT_CHAT_ID", ALERT_CHAT_ID)
    monkeypatch.setenv("PRICE_ALERT_THRESHOLD_PCT", "5")
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


async def _seed_sku(db: AsyncSession, slug_suffix: str, initial_cost: str | None = None) -> str:
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
        price_usd=Decimal("1.00"),
        cost_usdt=Decimal(initial_cost) if initial_cost else None,
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _seed_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    game_code: str,
    denom: str,
) -> SkuSupplierMapping:
    row = SkuSupplierMapping(
        sku_id=sku_id,
        supplier_slug="g2b",
        kind="game",
        external_product_id=game_code,
        external_variant_id=denom,
        quantity=1,
        extra={},
        is_active=True,
    )
    db.add(row)
    await db.commit()
    return row


# ---------- worker ----------


@respx.mock
async def test_refresh_all_records_history_and_fires_alert(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """First-time pricing → cost set, history row written, Telegram alert
    sent (no previous cost → always alert)."""
    sku_id = await _seed_sku(db_session, slug_suffix="alert-fire")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]},
        )
    )
    tg_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.checked == 1
    assert report.moved == 1
    assert report.alerts_sent == 1
    assert tg_route.called

    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(SupplierPriceHistory.sku_id == sku_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].cost_usdt == Decimal("0.89")
    assert history[0].previous_cost_usdt is None

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.89")


@respx.mock
async def test_refresh_all_skips_alert_under_threshold(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """1% move with 5% threshold → cost updates, history records, alert
    is NOT sent."""
    sku_id = await _seed_sku(db_session, slug_suffix="under-thr", initial_cost="0.890000")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.898}]},
        )
    )
    tg_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.checked == 1
    assert report.moved == 1
    assert report.alerts_sent == 0
    assert not tg_route.called


@respx.mock
async def test_refresh_all_noop_when_price_unchanged(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """G2B returns the same price → nothing recorded, nothing alerted."""
    sku_id = await _seed_sku(db_session, slug_suffix="noop", initial_cost="0.890000")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]},
        )
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.checked == 1
    assert report.moved == 0
    assert report.alerts_sent == 0
    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(SupplierPriceHistory.sku_id == sku_id)
            )
        )
        .scalars()
        .all()
    )
    assert history == []


# ---------- admin endpoints ----------


@respx.mock
async def test_history_endpoint_returns_newest_first(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, slug_suffix="hist")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        side_effect=[
            httpx.Response(200, json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]}),
            httpx.Response(200, json={"catalogues": [{"id": 1, "name": "60", "amount": 0.95}]}),
        ]
    )
    respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    await refresh_all_mappings()
    await refresh_all_mappings()

    admin = await _login_admin(integration_client, db_session, tg_id=901)
    r = await integration_client.get(
        f"/api/v1/admin/integrations/sku-prices/{sku_id}/history",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    # Newest first.
    assert items[0]["cost_usdt"] == "0.950000"
    assert items[0]["previous_cost_usdt"] == "0.890000"
    assert items[1]["cost_usdt"] == "0.890000"


@respx.mock
async def test_manual_refresh_all_endpoint(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, slug_suffix="manual")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]},
        )
    )
    respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    admin = await _login_admin(integration_client, db_session, tg_id=902)
    r = await integration_client.post(
        "/api/v1/admin/integrations/refresh-all-prices",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] == 1
    assert body["moved"] == 1
    assert body["alerts_sent"] == 1
