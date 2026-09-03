"""Checkout re-prices a Steam gift order line server-side, from the same
G-Engine detail the gifts catalog browses, with a ±2 % tolerance against the
client's proposed amount — the price actually billed is always the
server's own number. Mirrors ``test_checkout_variable_amount.py``: log in
via the Telegram webapp auth flow, POST ``/api/v1/orders``, assert on the
response and the persisted row.

The real gift SKU/product seed lands in a later task; the fixture here
builds a minimal Category -> Brand -> Product(``required_fields`` for
``app_id``/``package_id``/``region``/``invite_url``) -> Sku(``sku_code =
"steam-gift"``, ``variable_amount = True``) the same way
``test_checkout_variable_amount.py`` builds ``_variable_sku``.

G-Engine is mocked with respx (no outbound HTTP); the feature flag and
G-Engine credentials are set per test via ``monkeypatch.setenv`` +
``get_settings.cache_clear()``, the same pattern
``test_gifts_catalog_routes.py`` uses.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import fakeredis.aioredis
import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fx.providers.base import FxProvider, Quote
from yupay.modules.fx.service import FxService
from yupay.modules.orders.models import Order, OrderItem

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
BASE = "https://gengine.checkout.test/v2.1"
API_KEY = "gengine-checkout-test-key"
#: The SKU is variable-amount (Task 6), and ``_resolve_line_unit_price``
#: refuses USD for any variable-amount line — the gift SKU is priced and
#: charged in a local currency, converted at a guarded FX rate, same as the
#: Steam wallet top-up. See ``test_checkout_variable_amount.py``.
_UZS_RATE = Decimal("12700")

_REQUIRED_FIELDS: list[dict[str, Any]] = [
    {"key": "app_id", "type": "number", "required": True},
    {"key": "package_id", "type": "number", "required": True},
    {
        "key": "region",
        "type": "select",
        "required": True,
        "options": [{"value": "CIS"}, {"value": "RU"}],
    },
    {"key": "invite_url", "type": "text", "required": True},
]

_DEAD_CELLS_DETAIL: dict[str, Any] = {
    "id": 588650,
    "name": "Dead Cells",
    "type": "game",
    "packages": [
        {
            "id": 1,
            "name": "Standard Edition",
            "prices": [
                {"region": "CIS", "currency": "USD", "price": 1.00, "zone": "CIS"},
            ],
        }
    ],
}

_INVITE_URL = "https://steamcommunity.com/profiles/76561198000000000"


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


def _stub_fx_service() -> FxService:
    return FxService(
        providers=[_StubProvider({"UZS": _UZS_RATE})],
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )


@pytest.fixture(autouse=True)
def _fx(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guarded-rate trust gate ``_variable_line_charge`` (and any
    fixed-price, non-override line) goes through — same seam
    ``test_checkout_variable_amount.py`` patches."""
    monkeypatch.setattr("yupay.modules.pricing.fx_guard.build_default_service", _stub_fx_service)


@pytest.fixture(autouse=True)
def _gengine_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENGINE_API_KEY", API_KEY)
    monkeypatch.setenv("GENGINE_BASE_URL", BASE)
    monkeypatch.setenv("STEAM_GIFTS_MARGIN_PERCENT", "10")
    monkeypatch.setenv("STEAM_GIFTS_REGIONS", "CIS,RU")
    monkeypatch.setenv("STEAM_GIFTS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
async def _gift_sku(db_session: AsyncSession) -> Sku:
    """Category -> Brand -> Product(app_id/package_id/region/invite_url) ->
    variable-amount SKU with ``sku_code = "steam-gift"``."""
    category = Category(id=new_id(), slug="steam", sort_order=10, active=True)
    brand = Brand(id=new_id(), slug="steam", category_id=category.id, sort_order=10, active=True)
    sku = Sku(
        id=new_id(),
        sku_code="steam-gift",
        denomination=None,
        region=None,
        price_usd=Decimal("1"),
        variable_amount=True,
        min_amount_usd=Decimal("0.10"),
        max_amount_usd=Decimal("300.00"),
        rate_multiplier=Decimal("1.0000"),
        sort_order=10,
        active=True,
    )
    product = Product(
        id=new_id(),
        slug="steam-gift",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=_REQUIRED_FIELDS,
        skus=[sku],
    )
    db_session.add_all([category, brand, product])
    await db_session.commit()
    return sku


def _order_body(
    *,
    sku_id: str,
    amount_usd: str,
    app_id: int = 588650,
    package_id: int = 1,
    region: str = "CIS",
    invite_url: str = _INVITE_URL,
) -> dict[str, Any]:
    return {
        "currency": "UZS",
        "items": [
            {
                "sku_id": sku_id,
                "qty": 1,
                "amount_usd": amount_usd,
                "fulfillment_data": {
                    "app_id": app_id,
                    "package_id": package_id,
                    "region": region,
                    "invite_url": invite_url,
                },
            }
        ],
    }


def _mock_dead_cells() -> None:
    respx.get(f"{BASE}/gifts/apps/588650").mock(
        return_value=httpx.Response(200, json=_DEAD_CELLS_DETAIL)
    )


@respx.mock
async def test_happy_path_bills_the_server_price_and_enriches_the_snapshot(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _gift_sku: Sku,
) -> None:
    """$1.00 supplier * 10% margin = $1.10 expected — billed even though the
    client sent exactly that amount. The persisted OrderItem carries the
    canonical invite_url and the server-derived supplier_price_usd."""
    _mock_dead_cells()
    token = await _login_user(integration_client, tg_id=201)

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-happy-aaaaaaaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, amount_usd="1.10"),
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(body["items"][0]["unit_price_usd"]) == Decimal("1.10")
    assert Decimal(body["total_usd"]) == Decimal("1.10")

    order_id = body["id"]
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    ).scalar_one()
    assert item.fulfillment_data["supplier_price_usd"] == "1.0"
    assert item.fulfillment_data["invite_url"] == _INVITE_URL
    assert item.fulfillment_data["app_name"] == "Dead Cells"
    assert item.fulfillment_data["package_name"] == "Standard Edition"


@respx.mock
async def test_supplier_price_usd_never_reaches_the_customer_response(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _gift_sku: Sku,
) -> None:
    """``supplier_price_usd`` is our wholesale cost — it must be readable off
    the persisted row (fulfilment/audit needs it) but redacted from the
    order response the buyer receives, or the buyer could back out our exact
    margin as ``unit_price_usd - supplier_price_usd``."""
    _mock_dead_cells()
    token = await _login_user(integration_client, tg_id=206)

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-redact-aaaaaaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, amount_usd="1.10"),
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert "supplier_price_usd" not in body["items"][0]["fulfillment_data"]
    # The rest of the enriched snapshot is still customer-visible.
    assert body["items"][0]["fulfillment_data"]["app_name"] == "Dead Cells"

    order_id = body["id"]
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    ).scalar_one()
    assert item.fulfillment_data["supplier_price_usd"] == "1.0"


@respx.mock
async def test_a_schemeless_trailing_slash_invite_url_is_canonicalized_on_the_row(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _gift_sku: Sku,
) -> None:
    """Round-trips through validate_fulfillment_data (a plain ``text`` field,
    no pattern) and the checkout hook's own parse_invite_url — the row ends
    up with the canonical form regardless of what the client submitted."""
    _mock_dead_cells()
    token = await _login_user(integration_client, tg_id=202)

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-canonical-aaaaaaaaaa",
        },
        json=_order_body(
            sku_id=_gift_sku.id,
            amount_usd="1.10",
            invite_url="steamcommunity.com/profiles/76561198000000000/",
        ),
    )

    assert r.status_code == 201, r.text
    order_id = r.json()["id"]
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    ).scalar_one()
    assert item.fulfillment_data["invite_url"] == _INVITE_URL


@respx.mock
async def test_price_drifted_beyond_tolerance_is_a_422_with_expected_amount(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _gift_sku: Sku,
) -> None:
    """Expected is $1.10; $1.50 is well past the 2% band."""
    _mock_dead_cells()
    token = await _login_user(integration_client, tg_id=203)

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-drift-aaaaaaaaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, amount_usd="1.50"),
    )

    assert r.status_code == 422, r.text
    assert r.json()["extra"]["expected_amount_usd"] == "1.10"
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert rows == []


@respx.mock
async def test_disabled_flag_is_a_422(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _gift_sku: Sku,
) -> None:
    monkeypatch.setenv("STEAM_GIFTS_ENABLED", "false")
    cfg.get_settings.cache_clear()
    token = await _login_user(integration_client, tg_id=204)

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-disabled-aaaaaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, amount_usd="1.10"),
    )

    assert r.status_code == 422, r.text
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert rows == []


@respx.mock
async def test_bad_region_is_a_422(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _gift_sku: Sku,
) -> None:
    """ "XX" isn't declared on the product's ``region`` select options, so
    ``validate_fulfillment_data`` itself already rejects it before the
    checkout hook is ever reached."""
    _mock_dead_cells()
    token = await _login_user(integration_client, tg_id=205)

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "gift-bad-region-aaaaaaaa",
        },
        json=_order_body(sku_id=_gift_sku.id, amount_usd="1.10", region="XX"),
    )

    assert r.status_code == 422, r.text
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert rows == []
