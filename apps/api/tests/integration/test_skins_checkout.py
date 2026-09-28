"""A skin order line is priced from the live listing it names (plan 3a, Task 3)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.listings import Listing
from yupay.modules.skins.models import SkinItem, SkinTradeLink
from yupay.modules.skins.pricing import DEFAULT_RULES, quote
from yupay.modules.users.models import SteamLink

from tests.integration.test_checkout_steam_gift import _login_user, _stub_fx_service

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"
OTHER_STEAM_ID = 76561198000000001
SLUG = "ak-47-redline-field-tested"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    monkeypatch.setattr("yupay.modules.pricing.fx_guard.build_default_service", _stub_fx_service)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
def listings(monkeypatch: pytest.MonkeyPatch) -> list[Listing]:
    """What Waxpeer lists right now for the item (the checkout seam)."""
    live = [
        Listing(53860909078, 27867, 0.25, 1, [], None, "bot"),
        Listing(53860909079, 29000, 0.16, 2, [], None, "bot"),
    ]

    async def fake(_item: object) -> list[Listing]:
        return live

    monkeypatch.setattr("yupay.modules.skins.checkout.live_listings", fake)
    return live


@pytest.fixture
async def sku(db_session: AsyncSession) -> Sku:
    category = Category(id=new_id(), slug="steam", sort_order=10, active=True)
    brand = Brand(id=new_id(), slug="cs2-skins", category_id=category.id, active=True)
    sku = Sku(
        id=new_id(),
        sku_code="cs2-skin",
        price_usd=Decimal("1"),
        variable_amount=True,
        min_amount_usd=Decimal("0.20"),
        max_amount_usd=Decimal("10000"),
        rate_multiplier=Decimal("1"),
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="cs2-skin",
        brand_id=brand.id,
        kind="top_up",
        active=True,
        required_fields=[
            {"key": "slug", "label": {"ru": "s"}, "type": "text", "required": True},
            {"key": "listing_id", "label": {"ru": "l"}, "type": "number", "required": True},
            {"key": "tradelink", "label": {"ru": "t"}, "type": "text", "required": True},
        ],
        skus=[sku],
    )
    item = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug=SLUG,
        category="rifles",
        weapon="AK-47",
        skin="Redline",
        exterior="FT",
        search_text="ak-47 redline",
        min_auto_units=27867,
        count_auto=40,
        active=True,
    )
    db_session.add_all([category, brand, product, item])
    await db_session.commit()
    return sku


def _price(units: int) -> Decimal:
    return quote(
        units, rules=DEFAULT_RULES, category="rifles", weapon="AK-47", count_auto=40
    ).price_usd


def _body(sku_id: str, *, amount: Decimal, listing_id: int = 53860909078) -> dict[str, Any]:
    return {
        "currency": "UZS",
        "items": [
            {
                "sku_id": sku_id,
                "qty": 1,
                "amount_usd": str(amount),
                "fulfillment_data": {"slug": SLUG, "listing_id": listing_id, "tradelink": LINK},
            }
        ],
    }


async def _order(client: AsyncClient, token: str | None, body: dict[str, Any], key: str) -> Any:
    headers = {"Idempotency-Key": key.ljust(20, "x")}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post("/api/v1/orders", headers=headers, json=body)


async def test_the_listing_price_is_billed_and_snapshotted(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    sku: Sku,
    listings: list[Listing],
) -> None:
    token = await _login_user(integration_client, tg_id=930_001)
    r = await _order(integration_client, token, _body(sku.id, amount=_price(27867)), "skin-ok")
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["items"][0]["unit_price_usd"]) == _price(27867)
    # What we pay Waxpeer never reaches the customer.
    assert "expected_units" not in r.json()["items"][0]["fulfillment_data"]
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == r.json()["id"]))
    ).scalar_one()
    data = item.fulfillment_data
    assert data["expected_units"] == 27867
    assert data["market_hash_name"] == "AK-47 | Redline (Field-Tested)"
    assert data["tradelink"] == LINK
    # The link is remembered for next time.
    saved = (await db_session.execute(select(SkinTradeLink))).scalar_one()
    assert saved.url == LINK


async def test_a_guest_cannot_buy_a_skin(
    integration_client: AsyncClient, sku: Sku, listings: list[Listing]
) -> None:
    from tests.integration.test_guest_payment_flow import GUEST_EMAIL, _guest_token

    guest = await _guest_token(integration_client)
    body = {**_body(sku.id, amount=_price(27867)), "guest_email": GUEST_EMAIL}
    r = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Guest {guest}", "Idempotency-Key": "skin-guest-padpadpad"},
        json=body,
    )
    assert r.status_code == 401, r.text


async def test_a_link_to_another_steam_account_is_refused(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    sku: Sku,
    listings: list[Listing],
) -> None:
    token = await _login_user(integration_client, tg_id=930_002)
    me = (
        await integration_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
    ).json()
    db_session.add(SteamLink(id=new_id(), user_id=me["id"], steam_id=OTHER_STEAM_ID))
    await db_session.commit()
    r = await _order(integration_client, token, _body(sku.id, amount=_price(27867)), "skin-other")
    assert r.status_code == 422, r.text
    assert r.json()["extra"]["reason"] == "tradelink_other_account"


async def test_a_gone_listing_offers_the_next_one(
    integration_client: AsyncClient, sku: Sku, listings: list[Listing]
) -> None:
    token = await _login_user(integration_client, tg_id=930_003)
    body = _body(sku.id, amount=_price(27867), listing_id=1)
    r = await _order(integration_client, token, body, "skin-gone")
    assert r.status_code == 422, r.text
    extra = r.json()["extra"]
    assert extra["reason"] == "listing_gone"
    assert extra["next_offer"]["listing_id"] == 53860909078
    assert Decimal(extra["next_offer"]["price_usd"]) == _price(27867)


async def test_a_moved_price_is_refused_with_the_new_one(
    integration_client: AsyncClient, sku: Sku, listings: list[Listing]
) -> None:
    token = await _login_user(integration_client, tg_id=930_004)
    r = await _order(integration_client, token, _body(sku.id, amount=Decimal("1.00")), "skin-drift")
    assert r.status_code == 422, r.text
    assert Decimal(r.json()["extra"]["expected_amount_usd"]) == _price(27867)


async def test_a_skin_is_bought_on_an_order_of_its_own(
    integration_client: AsyncClient, sku: Sku, listings: list[Listing]
) -> None:
    # One skin failing refunds its whole order to the balance, so nothing else may ride
    # along — a declined cheap skin would otherwise refund a delivered second line.
    token = await _login_user(integration_client, tg_id=930_005)
    line = _body(sku.id, amount=_price(27867))["items"][0]
    body = {
        "currency": "UZS",
        "items": [
            line,
            {
                **line,
                "fulfillment_data": {**line["fulfillment_data"], "listing_id": 53860909079},
                "amount_usd": str(_price(29000)),
            },
        ],
    }
    r = await _order(integration_client, token, body, "skin-two-lines")
    assert r.status_code == 422, r.text
    assert r.json()["extra"]["reason"] == "skin_order_single_line"
