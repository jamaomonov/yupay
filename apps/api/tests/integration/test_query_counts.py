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
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
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
