"""List endpoints must issue O(1) SQL queries, not O(rows) (AGENTS.md §10).

The assertion style is self-calibrating: the same request is measured with 1
row and with 5 — the counts must be EQUAL. Any per-row lazy load (N+1) makes
the second measurement larger and fails without hardcoding fragile absolute
numbers. Each endpoint gets one untracked warm-up call first so one-time
work (fx snapshots, caches) doesn't skew the baseline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
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
from yupay.modules.fx.providers.base import FxProvider, Quote
from yupay.modules.fx.service import FxService
from yupay.modules.merchants.models import Merchant
from yupay.modules.orders.models import Order
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet import service as wallet_svc
from yupay.modules.wallet.service import Leg

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
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:
    """Counts every cursor execution on the engine the app is wired to."""
    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def _measure_get(
    client: AsyncClient, counter: dict[str, int], url: str, headers: dict[str, str] | None = None
) -> int:
    counter["n"] = 0
    r = await client.get(url, headers=headers or {})
    assert r.status_code == 200, r.text
    # Guard against a dead counter: 0 == 0 would green-light anything.
    assert counter["n"] > 0, "sql_counter saw no queries — listener not wired to the app engine"
    return counter["n"]


def _seed_catalog_unit(db: AsyncSession, n: int) -> str:
    """Add one category+brand+product+sku unit; returns the sku id."""
    category = Category(
        id=new_id(),
        slug=f"cat-{n}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}",
        category_id=category.id,
        sort_order=n,
        active=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=n,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{n}",
        denomination=str(n),
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=n,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


async def test_catalog_brands_listing_is_o1(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    _seed_catalog_unit(db_session, 1)
    await db_session.commit()

    await integration_client.get("/api/v1/catalog/brands")  # warm-up, untracked
    with_one = await _measure_get(integration_client, sql_counter, "/api/v1/catalog/brands")

    for n in range(2, 6):
        _seed_catalog_unit(db_session, n)
    await db_session.commit()

    with_five = await _measure_get(integration_client, sql_counter, "/api/v1/catalog/brands")
    assert with_five == with_one, f"brands list grew from {with_one} to {with_five} queries"


class _StubProvider(FxProvider):
    """Always answers with the fixed rate handed to it — no outbound HTTP.
    Mirrors the stub in test_checkout_variable_amount.py."""

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


def _stub_fx_service(rates: dict[str, Decimal]) -> FxService:
    return FxService(
        providers=[_StubProvider(rates)],
        redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )


def _seed_variable_sku(db: AsyncSession, *, product_id: str, n: int) -> None:
    """Add one variable-amount SKU to an existing product."""
    db.add(
        Sku(
            id=new_id(),
            product_id=product_id,
            sku_code=f"var-sku-{n}",
            price_usd=Decimal("1"),
            variable_amount=True,
            min_amount_usd=Decimal("1.00"),
            max_amount_usd=Decimal("300.00"),
            rate_multiplier=Decimal("1.0800"),
            sort_order=n,
            active=True,
        )
    )


async def test_catalog_product_detail_variable_skus_is_o1(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    sql_counter: dict[str, int],
) -> None:
    """A product page with several variable-amount SKUs must not re-derive
    the guarded FX rate once per SKU (each check is several SQL statements) —
    see the per-request ``rate_cache`` threaded through catalog.service's
    _resolve_price / _resolve_variable_price."""
    monkeypatch.setattr(
        "yupay.modules.pricing.fx_guard.build_default_service",
        lambda: _stub_fx_service({"UZS": Decimal("13000")}),
    )
    category = Category(id=new_id(), slug="wallets-qc", sort_order=1, active=True)
    brand = Brand(id=new_id(), slug="steam-qc", category_id=category.id, sort_order=1, active=True)
    product = Product(
        id=new_id(),
        slug="steam-wallet-qc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
    )
    db_session.add_all([category, brand, product])
    _seed_variable_sku(db_session, product_id=product.id, n=1)
    await db_session.commit()

    url = f"/api/v1/catalog/products/{product.slug}?currency=UZS"
    await integration_client.get(url)  # warm-up, untracked (creates the fx snapshot row)
    with_one = await _measure_get(integration_client, sql_counter, url)

    for n in range(2, 6):
        _seed_variable_sku(db_session, product_id=product.id, n=n)
    await db_session.commit()

    with_five = await _measure_get(integration_client, sql_counter, url)
    assert with_five == with_one, (
        f"product detail with 5 variable SKUs grew from {with_one} to {with_five} queries "
        "— guarded rate is being re-derived per SKU instead of memoized per request"
    )


async def test_catalog_categories_listing_is_o1(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    _seed_catalog_unit(db_session, 1)
    await db_session.commit()

    await integration_client.get("/api/v1/catalog/categories")
    with_one = await _measure_get(integration_client, sql_counter, "/api/v1/catalog/categories")

    for n in range(2, 6):
        _seed_catalog_unit(db_session, n)
    await db_session.commit()

    with_five = await _measure_get(integration_client, sql_counter, "/api/v1/catalog/categories")
    assert with_five == with_one, f"categories list grew from {with_one} to {with_five} queries"


async def _create_order(client: AsyncClient, *, token: str, sku_id: str, key: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_my_orders_listing_is_o1(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    sku_id = _seed_catalog_unit(db_session, 1)
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=701)
    headers = {"Authorization": f"Bearer {token}"}

    await _create_order(integration_client, token=token, sku_id=sku_id, key="qc-orders-01-pad")
    await integration_client.get("/api/v1/orders", headers=headers)
    with_one = await _measure_get(integration_client, sql_counter, "/api/v1/orders", headers)

    for n in range(2, 6):
        await _create_order(
            integration_client, token=token, sku_id=sku_id, key=f"qc-orders-{n:02d}-pad"
        )
    with_five = await _measure_get(integration_client, sql_counter, "/api/v1/orders", headers)
    assert with_five == with_one, f"orders list grew from {with_one} to {with_five} queries"


async def test_wallet_transactions_listing_is_o1(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    token = await _login_user(integration_client, tg_id=702)
    headers = {"Authorization": f"Bearer {token}"}
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 702)
        )
    ).scalar_one()

    user_acc = await wallet_svc.ensure_account(
        db_session, owner_type="user", owner_id=user_id, kind="user_wallet", currency="USD"
    )
    house_acc = await wallet_svc.ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_promo_expense", currency="USD"
    )

    async def _post_txn(i: int) -> None:
        await wallet_svc.post(
            db_session,
            kind="admin.adjust",
            legs=[
                Leg(account_id=user_acc.id, direction="D", amount=Decimal("1"), currency="USD"),
                Leg(account_id=house_acc.id, direction="C", amount=Decimal("1"), currency="USD"),
            ],
            idempotency_key=f"qc-wallet-{i}",
            actor="test",
        )
        await db_session.commit()

    await _post_txn(1)
    await integration_client.get("/api/v1/wallet/transactions", headers=headers)
    with_one = await _measure_get(
        integration_client, sql_counter, "/api/v1/wallet/transactions", headers
    )

    for i in range(2, 6):
        await _post_txn(i)
    with_five = await _measure_get(
        integration_client, sql_counter, "/api/v1/wallet/transactions", headers
    )
    assert with_five == with_one, f"wallet txns grew from {with_one} to {with_five} queries"


async def test_admin_payments_listing_is_o1(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    sku_id = _seed_catalog_unit(db_session, 1)
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=703)
    await _grant_admin(db_session, tg_id=703)
    headers = {"Authorization": f"Bearer {token}"}

    async def _make_payment(i: int) -> None:
        order_id = await _create_order(
            integration_client, token=token, sku_id=sku_id, key=f"qc-pay-order-{i:02d}-pad"
        )
        r = await integration_client.post(
            "/api/v1/payments/intents",
            headers={**headers, "Idempotency-Key": f"qc-pay-intent-{i:02d}-pad"},
            json={"order_id": order_id, "provider": "mock"},
        )
        assert r.status_code == 201, r.text

    await _make_payment(1)
    await integration_client.get("/api/v1/admin/payments", headers=headers)
    with_one = await _measure_get(
        integration_client, sql_counter, "/api/v1/admin/payments", headers
    )

    for i in range(2, 6):
        await _make_payment(i)
    with_five = await _measure_get(
        integration_client, sql_counter, "/api/v1/admin/payments", headers
    )
    assert with_five == with_one, f"admin payments grew from {with_one} to {with_five} queries"


async def test_admin_orders_listing_is_o1(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    """Merchant rows on the page must not cost a query each (M3c Task 2).

    The admin listing serves up to 500 rows and, since M3c, carries the
    reseller's **title** — which lives in another module's table. Reading it
    per row is the N+1 this file exists to catch, and it would only ever show
    up on B2B pages, which are the rarer ones to open. Every order below is a
    *merchant* order for exactly that reason: a page of retail rows asks for
    no titles at all and would pass a batched and an unbatched implementation
    alike.
    """
    token = await _login_user(integration_client, tg_id=707)
    await _grant_admin(db_session, tg_id=707)
    headers = {"Authorization": f"Bearer {token}"}

    async def _merchant_order(i: int) -> None:
        merchant_id = new_id()
        db_session.add(Merchant(id=merchant_id, title=f"Reseller {i}"))
        db_session.add(
            Order(
                id=new_id(),
                merchant_id=merchant_id,
                status="fulfilling",
                currency="USD",
                total_usd=Decimal("1.07"),
                total_charged=Decimal("1.07"),
                expires_at=now() + timedelta(minutes=10),
            )
        )
        await db_session.commit()

    await _merchant_order(1)
    await integration_client.get("/api/v1/admin/orders", headers=headers)
    with_one = await _measure_get(integration_client, sql_counter, "/api/v1/admin/orders", headers)

    for i in range(2, 6):
        await _merchant_order(i)
    with_five = await _measure_get(integration_client, sql_counter, "/api/v1/admin/orders", headers)
    assert with_five == with_one, f"admin orders grew from {with_one} to {with_five} queries"


@pytest.fixture
async def sql_log(db_engine) -> AsyncIterator[list[str]]:
    """Every statement the app issues, verbatim. `sql_counter` only counts, and
    a count cannot tell you *which* tables a request dragged in."""
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        seen.append(" ".join(statement.split()).lower())

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield seen
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def test_brand_listing_does_not_drag_in_the_whole_catalog(
    integration_client: AsyncClient, db_session: AsyncSession, sql_log: list[str]
) -> None:
    """`GET /catalog/brands` returns brand summaries — id, slug, name, logo. It
    must not touch products, SKUs, price overrides or FAQs.

    It did, because `Brand.products` and `Brand.faqs` are declared
    `lazy="selectin"` at the *model* level, so they fire on every query touching
    a Brand regardless of what the caller asked for — and the products then
    chain to their own SKUs. Measured on the production box: 14 statements and
    58ms of CPU for 18 brands, which on one event loop is a ceiling of about 17
    requests a second for the entire API.

    Asserted by table rather than by a count, because a count stays constant
    while the rows read grow with the catalog — which is exactly how this hid
    behind the O(1) test above.
    """
    for i in (1, 2, 3):
        _seed_catalog_unit(db_session, i)
    await db_session.commit()

    await integration_client.get("/api/v1/catalog/brands")  # warm-up, untracked
    sql_log.clear()
    r = await integration_client.get("/api/v1/catalog/brands")
    assert r.status_code == 200, r.text

    selects = [s for s in sql_log if s.startswith("select")]
    assert selects, "no statements captured — listener not wired to the app engine"

    unwanted = {
        "skus": "SKU rows",
        "brand_faqs": "FAQ rows",
        "brand_faq_translations": "FAQ translations",
        "sku_price_overrides": "price overrides",
    }
    touched = {
        table: why for table, why in unwanted.items() if any(f" {table}" in s for s in selects)
    }
    assert not touched, (
        "the brand list pulled in "
        + ", ".join(touched.values())
        + f" — {len(selects)} statements: "
        + "; ".join(s[:60] for s in selects)
    )
