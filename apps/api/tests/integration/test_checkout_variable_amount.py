"""Checkout accepts a customer-chosen amount for variable-amount SKUs (Steam
wallet top-ups): the amount is priced server-side against a guarded FX rate,
the supplier balance is preflighted before the order is persisted, and a
client can never smuggle its own price into the order.

Following the pattern in ``test_orders_routes.py``: log in via the Telegram
webapp auth flow, POST ``/api/v1/orders``, assert on the response and the
persisted row. FX is patched at ``yupay.modules.pricing.fx_guard`` (the same
seam ``test_fx_guard_db.py`` uses) so no outbound HTTP happens.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment.suppliers import REGISTRY
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.orders.models import Order

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


class _StubProvider(FxProvider):
    """Always answers with the fixed rate handed to it — no outbound HTTP."""

    name = "stub"

    def __init__(self, rates: dict[str, Decimal]) -> None:
        self._rates = rates

    def supports(self, base: str, quote: str) -> bool:
        return base.upper() == "USD" and quote.upper() in self._rates

    async def get_rate(self, base: str, quote: str) -> Quote:
        return Quote(
            base=base.upper(),
            quote=quote.upper(),
            rate=self._rates[quote.upper()],
            fetched_at=now(),
            source=self.name,
        )


class _FailingProvider(FxProvider):
    """Simulates the whole FX pipeline being down."""

    name = "failing"

    def supports(self, base: str, quote: str) -> bool:
        return True

    async def get_rate(self, base: str, quote: str) -> Quote:
        raise FxProviderError("upstream unreachable")


def _stub_fx_service(rates: dict[str, Decimal]) -> FxService:
    return FxService(
        providers=[_StubProvider(rates)],
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )


def _failing_fx_service() -> FxService:
    return FxService(
        providers=[_FailingProvider()],
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )


@pytest.fixture
async def _variable_sku(db_session: AsyncSession) -> Sku:
    """Category → Brand → Product(top_up) → variable-amount SKU ($1–$300,
    multiplier 1.08) — a Steam wallet top-up."""
    category = Category(id=new_id(), slug="wallets", sort_order=10, active=True)
    brand = Brand(id=new_id(), slug="steam", category_id=category.id, sort_order=10, active=True)
    sku = Sku(
        id=new_id(),
        sku_code="steam-wallet-variable",
        denomination=None,
        region=None,
        price_usd=Decimal("1"),
        variable_amount=True,
        min_amount_usd=Decimal("1.00"),
        max_amount_usd=Decimal("300.00"),
        rate_multiplier=Decimal("1.0800"),
        sort_order=10,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="steam-wallet",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        skus=[sku],
    )
    db_session.add_all([category, brand, product])
    await db_session.commit()
    return sku


@pytest.fixture
async def _fixed_sku(db_session: AsyncSession) -> Sku:
    """A perfectly ordinary fixed-price SKU, for the negative cases."""
    category = Category(id=new_id(), slug="games", sort_order=10, active=True)
    brand = Brand(
        id=new_id(), slug="pubg-mobile", category_id=category.id, sort_order=10, active=True
    )
    sku = Sku(
        id=new_id(),
        sku_code="pubg-uc-60",
        denomination="60 UC",
        region="TR",
        price_usd=Decimal("0.85"),
        sort_order=10,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        skus=[sku],
    )
    db_session.add_all([category, brand, product])
    await db_session.commit()
    return sku


def _order_body(
    *, sku_id: str, qty: int = 1, currency: str = "USD", amount_usd: str | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {"sku_id": sku_id, "qty": qty, "fulfillment_data": {}}
    if amount_usd is not None:
        item["amount_usd"] = amount_usd
    return {"currency": currency, "items": [item]}


async def test_variable_sku_prices_from_the_amount(
    integration_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _variable_sku: Sku,
) -> None:
    """$10 at a guarded market rate of 13000 and multiplier 1.08 charges 140 400 UZS."""
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("13000")}),
    )
    token = await _login_user(integration_client, tg_id=101)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "variable-happy-aaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, currency="UZS", amount_usd="10"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["currency"] == "UZS"
    assert Decimal(body["total_charged"]) == Decimal("140400")
    assert Decimal(body["total_usd"]) == Decimal("10")
    assert Decimal(body["items"][0]["unit_price_usd"]) == Decimal("10")


async def test_amount_is_required_for_a_variable_sku(
    integration_client: AsyncClient, _variable_sku: Sku
) -> None:
    """Omitting amount_usd is a 422, not a silent zero."""
    token = await _login_user(integration_client, tg_id=102)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "variable-missing-aaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id),
    )
    assert r.status_code == 422, r.text


async def test_amount_is_rejected_for_a_fixed_sku(
    integration_client: AsyncClient, _fixed_sku: Sku
) -> None:
    """Sending amount_usd for a normal SKU is a 422 — no ambiguity about price."""
    token = await _login_user(integration_client, tg_id=103)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "fixed-with-amount-aaaaaa",
        },
        json=_order_body(sku_id=_fixed_sku.id, amount_usd="5"),
    )
    assert r.status_code == 422, r.text


async def test_amount_outside_the_sku_bounds_is_rejected(
    integration_client: AsyncClient, _variable_sku: Sku
) -> None:
    """$301 against a $1-$300 SKU is a 422."""
    token = await _login_user(integration_client, tg_id=104)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "out-of-bounds-aaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, amount_usd="301"),
    )
    assert r.status_code == 422, r.text


async def test_client_supplied_price_is_ignored(
    integration_client: AsyncClient, _variable_sku: Sku
) -> None:
    """The order total comes from the server's computation, never the request:
    a client that also tries to smuggle its own price field is rejected
    outright rather than having that field silently honoured."""
    token = await _login_user(integration_client, tg_id=105)
    body = _order_body(sku_id=_variable_sku.id, amount_usd="10")
    body["items"][0]["unit_price_usd"] = "0.01"
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "smuggled-price-aaaaaaaa",
        },
        json=body,
    )
    assert r.status_code == 422, r.text


async def test_rejected_rate_makes_checkout_fail_closed(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _variable_sku: Sku,
) -> None:
    """With the FX guard tripped, checkout answers 502 and no order is created."""
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        _failing_fx_service,
    )
    token = await _login_user(integration_client, tg_id=106)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "rate-rejected-aaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, currency="UZS", amount_usd="10"),
    )
    assert r.status_code == 502, r.text
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert rows == []


async def test_checkout_refused_when_supplier_balance_is_short(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _variable_sku: Sku,
) -> None:
    """Waxpeer balance below the gross needed => 502 and no order row."""
    db_session.add(
        SkuSupplierMapping(
            sku_id=_variable_sku.id,
            supplier_slug="waxpeer",
            kind="game",
            external_product_id="steam-wallet",
            is_active=True,
        )
    )
    await db_session.commit()
    monkeypatch.setattr(REGISTRY["waxpeer"], "has_balance", AsyncMock(return_value=False))

    token = await _login_user(integration_client, tg_id=107)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "low-balance-aaaaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, amount_usd="10"),
    )
    assert r.status_code == 502, r.text
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert rows == []
