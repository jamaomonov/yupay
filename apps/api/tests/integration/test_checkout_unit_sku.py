"""Checkout for a "unit SKU" (Telegram Stars, sold as integer qty of a named
unit, see ``yupay.modules.catalog.unit_sku``) and the fraud control that must
ride along with it.

``OrderItemIn.qty``'s wire ceiling was raised from 100 to ``UNIT_QTY_WIRE_MAX``
(50 000) so a unit SKU can be bought in bulk. That is not a real limit for
anything else — the real limit is the SKU's own ``min_qty``/``max_qty`` for a
unit SKU, and ``DEFAULT_QTY_MAX`` (100) for every ordinary, fixed-price SKU.
``test_a_fixed_gift_card_still_rejects_qty_over_100`` is the security
regression: it proves the raised wire ceiling did not leak into the general
case.

Follows the fixture/auth pattern of ``test_checkout_variable_amount.py``
exactly (Telegram webapp login, POST ``/api/v1/orders``) rather than inventing
a new one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku, SkuPrice

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


@pytest.fixture
async def _unit_sku(db_session: AsyncSession) -> Sku:
    """A Telegram Stars unit SKU: 0.02 USD/star, 50-2500 stars, with a UZS
    per-unit override (250 so'm/star) so the override-price branch of
    ``_compute_total_charged`` is exercised the same way a real Stars sale
    would be."""
    category = Category(id=new_id(), slug="telegram", sort_order=10, active=True)
    brand = Brand(
        id=new_id(), slug="telegram-stars", category_id=category.id, sort_order=10, active=True
    )
    sku = Sku(
        id=new_id(),
        sku_code="telegram-stars-unit",
        denomination=None,
        region=None,
        price_usd=Decimal("0.02"),
        variable_amount=False,
        amount_unit="Stars",
        min_qty=50,
        max_qty=2500,
        sort_order=10,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="telegram-stars",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        skus=[sku],
    )
    db_session.add_all([category, brand, product])
    await db_session.commit()
    db_session.add(SkuPrice(sku_id=sku.id, currency="UZS", price=Decimal("250.00")))
    await db_session.commit()
    return sku


@pytest.fixture
async def _gift_sku(db_session: AsyncSession) -> Sku:
    """An ordinary fixed-price SKU (not a unit SKU) — the negative case that
    proves the raised wire ceiling did not raise the real limit for it too."""
    category = Category(id=new_id(), slug="games", sort_order=10, active=True)
    brand = Brand(
        id=new_id(), slug="steam-giftcard", category_id=category.id, sort_order=10, active=True
    )
    sku = Sku(
        id=new_id(),
        sku_code="steam-giftcard-20",
        denomination="$20",
        region="US",
        price_usd=Decimal("20"),
        sort_order=10,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="steam-giftcard",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        skus=[sku],
    )
    db_session.add_all([category, brand, product])
    await db_session.commit()
    return sku


def _order_body(*, sku_id: str, qty: int, currency: str = "USD") -> dict[str, Any]:
    return {
        "currency": currency,
        "items": [{"sku_id": sku_id, "qty": qty, "fulfillment_data": {}}],
    }


async def test_qty_500_charges_500_times_the_star_price(
    integration_client: AsyncClient, _unit_sku: Sku
) -> None:
    """500 stars at the 250 so'm/star UZS override charges 125 000 so'm."""
    token = await _login_user(integration_client, tg_id=201)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "unit-sku-qty500-aaaaaaa",
        },
        json=_order_body(sku_id=_unit_sku.id, qty=500, currency="UZS"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["items"][0]["qty"] == 500
    assert Decimal(body["total_charged"]) == Decimal("125000")


async def test_qty_below_min_is_422(integration_client: AsyncClient, _unit_sku: Sku) -> None:
    token = await _login_user(integration_client, tg_id=202)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "unit-sku-qty-low-aaaaaa",
        },
        json=_order_body(sku_id=_unit_sku.id, qty=49, currency="UZS"),
    )
    assert r.status_code == 422, r.text


async def test_qty_above_max_is_422(integration_client: AsyncClient, _unit_sku: Sku) -> None:
    token = await _login_user(integration_client, tg_id=203)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "unit-sku-qty-high-aaaaa",
        },
        json=_order_body(sku_id=_unit_sku.id, qty=2501, currency="UZS"),
    )
    assert r.status_code == 422, r.text


async def test_amount_usd_on_a_unit_sku_is_422(
    integration_client: AsyncClient, _unit_sku: Sku
) -> None:
    """A unit SKU takes the fixed-price path — sending amount_usd is the same
    illegal combination as on any other fixed-price SKU."""
    token = await _login_user(integration_client, tg_id=204)
    body = _order_body(sku_id=_unit_sku.id, qty=50, currency="UZS")
    body["items"][0]["amount_usd"] = "1"
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "unit-sku-amount-aaaaaaa",
        },
        json=body,
    )
    assert r.status_code == 422, r.text


async def test_a_fixed_gift_card_still_rejects_qty_over_100(
    integration_client: AsyncClient, _gift_sku: Sku
) -> None:
    """Security: the raised wire max (50 000) must not apply to ordinary
    SKUs — a non-unit SKU is still capped at DEFAULT_QTY_MAX (100)."""
    token = await _login_user(integration_client, tg_id=205)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-sku-qty101-aaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, qty=101, currency="USD"),
    )
    assert r.status_code == 422, r.text


async def test_a_fixed_gift_card_allows_qty_up_to_100(
    integration_client: AsyncClient, _gift_sku: Sku
) -> None:
    """The unraised half of the same boundary: qty=100 on an ordinary SKU is
    still legal, so the gate below the wire max didn't move either."""
    token = await _login_user(integration_client, tg_id=206)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-sku-qty100-aaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, qty=100, currency="USD"),
    )
    assert r.status_code == 201, r.text


async def test_usd_sale_of_stars_is_allowed(
    integration_client: AsyncClient, _unit_sku: Sku
) -> None:
    """A unit SKU has a real ``price_usd`` (unlike Steam's variable-amount
    path), so — unlike a variable-amount line — a USD sale is legal."""
    token = await _login_user(integration_client, tg_id=207)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "unit-sku-usd-aaaaaaaaaa",
        },
        json=_order_body(sku_id=_unit_sku.id, qty=50, currency="USD"),
    )
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["total_charged"]) == Decimal("1.00")
