"""``/admin/skins/pricing``: read defaults, replace, preview explains, item override
changes the storefront price, and a replaced document expires cached pages."""

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
from yupay.core import config as cfg
from yupay.core.ids import new_id
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.pricing import DEFAULT_RULES
from yupay.modules.skins.repricing import reprice_rows
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


async def _admin_headers(client: AsyncClient, db: AsyncSession, tg_id: int) -> dict[str, str]:
    token = await _login_user(client, tg_id=tg_id)
    await _grant_admin(db, tg_id=tg_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def headers(integration_client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    return await _admin_headers(integration_client, db_session, tg_id=910_001)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
async def ak(db_session: AsyncSession) -> SkinItem:
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug="ak-47-redline-field-tested",
        category="rifles",
        search_text="ak 47 redline field tested",
        min_auto_units=27867,
        count_auto=49,
        active=True,
        cheapest_auto=[{"listing_id": 1, "price_units": 27867}],
    )
    db_session.add(row)
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    return row


async def test_get_returns_defaults(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await integration_client.get("/api/v1/admin/skins/pricing", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["rules"]["retail"][0] == {"from_usd": "0", "percent": "10"}
    assert body["rules"]["expenses_percent"] == "3"
    assert body["rules"]["liquidity"][0] == {"min_count": 50, "pp": "-1"}


async def test_preview_explains_the_number(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/skins/pricing/preview",
        params={"cost_usd": "27.867", "category": "stickers", "count": "2"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    # 1.80069 margin + (3 % + 5 pp stickers + 3 pp for 2 listings) × 27.867 = 3.06537 -> 32.73306 -> 32.74
    assert (body["price_usd"], body["applied"]) == ("32.74", "formula")
    assert (body["category_pp"], body["liquidity_pp"], body["expenses_usd"]) == (
        "5",
        "3",
        "0.83601",
    )


async def test_put_replaces_and_reprices_the_storefront(
    integration_client: AsyncClient, headers: dict[str, str], ak: SkinItem
) -> None:
    before = (await integration_client.get(f"/api/v1/skins/{ak.slug}")).json()["price_usd"]
    assert before == "30.37"
    r = await integration_client.get("/api/v1/admin/skins/pricing", headers=headers)
    rules = r.json()["rules"]
    rules["retail"] = [{"from_usd": "0", "percent": "50"}]
    r = await integration_client.put("/api/v1/admin/skins/pricing", json=rules, headers=headers)
    assert r.status_code == 200
    after = (await integration_client.get(f"/api/v1/skins/{ak.slug}")).json()["price_usd"]
    assert after == "42.50"  # 13.9335 margin + 2.5 pp × 27.867 = 0.6967 -> 42.4972 -> ceil


async def test_put_refuses_brackets_that_do_not_start_at_zero(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await integration_client.get("/api/v1/admin/skins/pricing", headers=headers)
    rules = r.json()["rules"]
    rules["retail"] = [{"from_usd": "5", "percent": "10"}]
    r = await integration_client.put("/api/v1/admin/skins/pricing", json=rules, headers=headers)
    assert r.status_code == 422


async def test_item_override_pins_a_price_while_it_covers_cost(
    integration_client: AsyncClient, headers: dict[str, str], ak: SkinItem
) -> None:
    url = f"/api/v1/admin/skins/items/{ak.slug}"
    r = await integration_client.patch(url, json={"fixed_price_usd": "35.00"}, headers=headers)
    assert r.status_code == 200
    assert (await integration_client.get(f"/api/v1/skins/{ak.slug}")).json()["price_usd"] == "35.00"
    await integration_client.patch(url, json={"fixed_price_usd": "20.00"}, headers=headers)
    assert (await integration_client.get(f"/api/v1/skins/{ak.slug}")).json()["price_usd"] == "30.37"
    r = await integration_client.patch("/api/v1/admin/skins/items/nope", json={}, headers=headers)
    assert r.status_code == 404


async def test_item_patch_changes_only_the_fields_sent_and_replays(
    integration_client: AsyncClient, headers: dict[str, str], ak: SkinItem
) -> None:
    url = f"/api/v1/admin/skins/items/{ak.slug}"
    await integration_client.patch(url, json={"fixed_price_usd": "35.00"}, headers=headers)
    r = await integration_client.patch(url, json={"margin_override_pp": "5"}, headers=headers)
    body = r.json()
    assert Decimal(body["margin_override_pp"]) == Decimal(5)
    assert Decimal(body["fixed_price_usd"]) == Decimal("35.00")  # not cleared by omission
    keyed = {**headers, "Idempotency-Key": "skins-patch-0000000000000001"}
    first = await integration_client.patch(url, json={"fixed_price_usd": None}, headers=keyed)
    await integration_client.patch(url, json={"fixed_price_usd": "40.00"}, headers=headers)
    replay = await integration_client.patch(url, json={"fixed_price_usd": None}, headers=keyed)
    assert replay.json() == first.json()


async def test_listings_call_uses_the_short_timeout(
    integration_client: AsyncClient, ak: SkinItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.skins import routes

    seen: dict[str, float] = {}

    class _Spy:
        def __init__(self, **kwargs: object) -> None:
            seen["timeout"] = float(kwargs["timeout_seconds"])  # type: ignore[arg-type]

        async def search_listings(
            self, names: list[str], *, game: str = "csgo"
        ) -> dict[str, object]:
            return {}

    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    cfg.get_settings.cache_clear()
    monkeypatch.setattr(routes, "WaxpeerClient", _Spy)
    await integration_client.get(f"/api/v1/skins/{ak.slug}/listings")
    assert seen["timeout"] == 4.0
