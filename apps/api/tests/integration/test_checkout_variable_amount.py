"""Checkout accepts a customer-chosen amount for variable-amount SKUs (Steam
wallet top-ups): the amount is priced server-side against a guarded FX rate and
a client can never smuggle its own price into the order. A paid order is never
refused for the supplier being short on balance — that surfaces as a soft
low-balance failure at fulfilment, not a checkout rejection.

Also covers the fixed-price, no-override, non-USD branch (``_fixed_sku``
below): it must run through the same FX trust gate as the variable-amount
branch, not a plain unguarded FX conversion — see
``test_fixed_sku_checkout_uses_the_guarded_fx_rate`` and
``test_fixed_sku_checkout_fails_closed_on_a_rejected_rate``.

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
from urllib.parse import urlencode

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.service import FxService
from yupay.modules.orders.models import Order, OrderItem

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


async def test_the_storefront_is_told_what_unit_the_amount_is_in(
    integration_client: AsyncClient,
    _variable_sku: Sku,
    db_session: AsyncSession,
) -> None:
    """The unit lives on the SKU and only reaches the customer through this
    DTO. It was added to the schema and left unpopulated once already, which
    reads as "priced in dollars" — so a stars field would have asked for
    dollars and priced them as stars."""
    _variable_sku.amount_unit = "Stars"
    _variable_sku.units_per_usd = Decimal("64.705882")
    await db_session.commit()

    r = await integration_client.get("/api/v1/catalog/products/steam-wallet?currency=UZS")

    assert r.status_code == 200, r.text
    sku = next(s for s in r.json()["skus"] if s["variable_amount"])
    assert sku["amount_unit"] == "Stars"
    assert Decimal(sku["units_per_usd"]) == Decimal("64.705882")


async def test_a_dollar_priced_sku_reports_no_unit(
    integration_client: AsyncClient,
    _variable_sku: Sku,
) -> None:
    # Every SKU that existed before this field. Absent must keep meaning
    # dollars, or the storefront starts converting by a rate that is not there.
    r = await integration_client.get("/api/v1/catalog/products/steam-wallet?currency=UZS")

    sku = next(s for s in r.json()["skus"] if s["variable_amount"])
    assert sku["amount_unit"] is None
    assert sku["units_per_usd"] is None


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
    # The client's only way to tell "this $10 is the credited amount" apart
    # from "this $10 is a catalog price shown for context" — a fixed SKU's
    # denomination already says what was bought, a variable one's doesn't.
    assert body["items"][0]["display"]["variable_amount"] is True


async def test_uzs_total_is_rounded_to_whole_sum(
    integration_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _variable_sku: Sku,
) -> None:
    """A fractional FX-derived UZS total is rounded to whole so'm, so the stored
    ``total_charged`` is always an exact tiyin amount every acquirer can charge.

    $10 × 12765.7325 × 1.08 = 137869.911 — six-decimal intermediate precision.
    Pre-rounding this is unpayable via Payme/Octo (137869.911 × 100 = 13786991.1,
    not an integer number of tiyin); rounded to whole so'm it is 137870.
    """
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("12765.7325")}),
    )
    token = await _login_user(integration_client, tg_id=120)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "uzs-rounding-aaaaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, currency="UZS", amount_usd="10"),
    )
    assert r.status_code == 201, r.text
    total = Decimal(r.json()["total_charged"])
    assert total == Decimal("137870")
    # Whole so'm ⇒ exact tiyin: no acquirer can reject it for a sub-unit remainder.
    assert total == total.to_integral_value()
    assert (total * 100) == (total * 100).to_integral_value()


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


async def test_checkout_rejects_a_sku_under_a_hidden_brand(
    integration_client: AsyncClient, _fixed_sku: Sku, db_session: AsyncSession
) -> None:
    """Deactivating a brand doesn't cascade to its SKUs, so checkout must reject
    an order for a still-active SKU whose brand an admin has hidden — otherwise
    a customer could pay for a product pulled from sale."""
    await db_session.execute(update(Brand).where(Brand.slug == "pubg-mobile").values(active=False))
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=104)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "hidden-brand-order-aaaa",
        },
        json=_order_body(sku_id=_fixed_sku.id),
    )
    assert r.status_code == 422, r.text


async def test_checkout_rejects_a_sku_under_a_brand_in_maintenance(
    integration_client: AsyncClient, _fixed_sku: Sku, db_session: AsyncSession
) -> None:
    """Maintenance is the softer 'temporarily unavailable' state — the brand
    still lists, but the model documents it as blocking purchases, so checkout
    must refuse an order for a SKU under a maintenance-mode brand."""
    await db_session.execute(
        update(Brand).where(Brand.slug == "pubg-mobile").values(maintenance=True)
    )
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=105)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "maintenance-order-aaaa",
        },
        json=_order_body(sku_id=_fixed_sku.id),
    )
    assert r.status_code == 422, r.text


async def test_qty_other_than_one_is_rejected_for_a_variable_sku(
    integration_client: AsyncClient, _variable_sku: Sku
) -> None:
    """Quantity is meaningless for a customer-chosen amount — buying "more"
    means entering a bigger amount, not qty=2. Fulfillment creates exactly
    one FulfillmentTask per OrderItem and bills the supplier for
    unit_price_usd with no × qty, so qty=2 would charge the customer twice
    while topping up the Steam wallet only once. Must 422 before pricing or
    fulfillment ever sees the line."""
    token = await _login_user(integration_client, tg_id=110)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "variable-qty2-aaaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, qty=2, amount_usd="10"),
    )
    assert r.status_code == 422, r.text


async def test_usd_checkout_is_rejected_for_a_variable_sku(
    integration_client: AsyncClient, _variable_sku: Sku
) -> None:
    """The pricing model for these SKUs is "USD amount × guarded local rate ×
    margin multiplier" — there is no margin-bearing USD price. A USD
    checkout would be face value at zero margin, so it must 422 instead of
    silently selling at (or below) cost."""
    token = await _login_user(integration_client, tg_id=111)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "variable-usd-aaaaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, currency="USD", amount_usd="10"),
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


async def test_checkout_accepts_order_even_when_supplier_balance_is_short(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _variable_sku: Sku,
) -> None:
    """A paid order is never refused for the supplier being short: checkout no
    longer preflights the Waxpeer balance. A short balance surfaces later as a
    soft low-balance failure at fulfilment (customer stays on "processing", ops
    alerted, admin tops up + retries) — see the fulfiller tests. Here we only
    prove checkout accepts and persists the order.
    """
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("13000")}),
    )
    # Checkout no longer touches the supplier balance at all — no stub needed;
    # the order goes through regardless of what Waxpeer's wallet holds.
    token = await _login_user(integration_client, tg_id=107)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "low-balance-aaaaaaaaaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, currency="UZS", amount_usd="10"),
    )
    assert r.status_code == 201, r.text
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert len(rows) == 1


async def test_fixed_sku_checkout_uses_the_guarded_fx_rate(
    integration_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _fixed_sku: Sku,
) -> None:
    """A fixed-price SKU with no per-currency override, checked out in a
    non-USD currency, is still priced from the FX *trust gate*, not a plain
    conversion — same as the variable-amount branch. $0.85 at a guarded rate
    of 13000 charges 11 050 UZS."""
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("13000")}),
    )
    token = await _login_user(integration_client, tg_id=112)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "fixed-guarded-ok-aaaaaa",
        },
        json=_order_body(sku_id=_fixed_sku.id, currency="UZS"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(body["total_charged"]) == Decimal("11050")
    # Audit trail: the order binds the exact snapshot the guarded rate came
    # from, same as any other FX-priced order.
    assert body["fx_snapshot_id"] is not None
    assert body["items"][0]["display"]["variable_amount"] is False


async def test_fixed_sku_checkout_fails_closed_on_a_rejected_rate(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _fixed_sku: Sku,
) -> None:
    """Regression test for the FX trust-gate bypass on this branch: a
    fixed-price, no-override, non-USD line used to call ``fx.snapshot``
    directly, skipping ``guarded_usd_rate`` — so a wrong or stale rate could
    still set the charged price. With the guard tripped (rate far outside
    the sane UZS band), checkout must fail closed: 502, no order persisted —
    the SKU falls out of sale for this currency rather than charging on an
    untrusted rate."""
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("500")}),  # below pricing_fx_min_rate_uzs
    )
    token = await _login_user(integration_client, tg_id=113)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "fixed-guarded-bad-aaaaa",
        },
        json=_order_body(sku_id=_fixed_sku.id, currency="UZS"),
    )
    assert r.status_code == 502, r.text
    rows = (await db_session.execute(select(Order))).scalars().all()
    assert rows == []


async def test_checkout_freezes_the_rate_the_line_was_priced_at(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _variable_sku: Sku,
) -> None:
    """ADR-0051: the multiplier and market rate that produced the charge are
    written onto the line.

    Without them the order's value in USD can only be recovered by re-reading
    a ``Sku.rate_multiplier`` an admin may since have changed — so raising the
    Steam margin would silently revalue every order ever sold.
    """
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("13000")}),
    )
    token = await _login_user(integration_client, tg_id=120)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "variable-pins-rate-aaaa",
        },
        json=_order_body(sku_id=_variable_sku.id, currency="UZS", amount_usd="10"),
    )
    assert r.status_code == 201, r.text

    item = (await db_session.execute(select(OrderItem))).scalars().one()
    assert item.rate_multiplier == _variable_sku.rate_multiplier
    # The *market* rate, pre-multiplier — the customer-facing rate is this
    # times the multiplier, and keeping the two apart is what lets the margin
    # be recovered later.
    assert item.fx_rate == Decimal("13000")


async def test_a_fixed_line_records_its_rate_but_no_multiplier(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _fixed_sku: Sku,
) -> None:
    """A fixed line has no markup in its rate — its USD value is already
    ``unit_price_usd`` — so the multiplier stays NULL. The rate it converted
    at is still worth keeping for "what did we quote them"."""
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("13000")}),
    )
    token = await _login_user(integration_client, tg_id=121)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "fixed-pins-rate-aaaaaa",
        },
        json=_order_body(sku_id=_fixed_sku.id, currency="UZS"),
    )
    assert r.status_code == 201, r.text

    item = (await db_session.execute(select(OrderItem))).scalars().one()
    assert item.rate_multiplier is None
    assert item.fx_rate == Decimal("13000")
