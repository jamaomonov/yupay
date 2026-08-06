"""Integration tests for ``/api/v1/orders/*`` and ``/api/v1/admin/orders/*``.

Covers:
- Create order as authenticated user + as guest
- Idempotency replay returns the same order
- required_fields validation (missing / wrong pattern)
- 404 for orders of another user
- Admin can list / cancel a pending order
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import event, update
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
    SkuPrice,
)
from yupay.modules.orders.models import Order, OrderItem
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
    body: dict[str, str] = r.json()
    return body["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    from sqlalchemy import select

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
    """Counts every cursor execution on the engine the app is wired to.

    Mirrors the fixture in ``test_query_counts.py`` (AGENTS.md §10: every
    list endpoint must have an integration test asserting query count) —
    duplicated locally rather than imported, matching this suite's existing
    convention of per-file test helpers (see ``_login_user``/``_grant_admin``
    above)."""
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


@pytest.fixture
async def _seed_pubg(db_session: AsyncSession) -> dict[str, str]:
    """Insert one category → brand → PUBG UC product → 1 SKU."""
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[
            CategoryTranslation(locale="ru", name="Игры"),
            CategoryTranslation(locale="en", name="Games"),
        ],
    )
    brand = Brand(
        id=new_id(),
        slug="pubg-mobile",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG Mobile")],
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[
            {
                "key": "player_id",
                "label": {"ru": "ID"},
                "type": "text",
                "required": True,
                "pattern": r"^[0-9]{6,15}$",
            },
            {
                "key": "server",
                "label": {"ru": "Сервер"},
                "type": "select",
                "required": True,
                "options": [
                    {"value": "as", "label": {"ru": "AS"}},
                    {"value": "eu", "label": {"ru": "EU"}},
                ],
            },
        ],
        translations=[ProductTranslation(locale="ru", name="UC")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-uc-60-tr",
        denomination="60 UC",
        region="TR",
        price_usd=Decimal("0.85"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return {"sku_id": sku.id, "product_id": product.id}


# ---------- create order ----------


async def test_create_order_requires_idempotency_key(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=11)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "123456", "server": "as"},
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "Idempotency-Key" in r.text


async def test_create_order_uses_sku_price_override(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    """When the SKU has a SkuPrice override for the order currency, the
    storefront must charge that exact figure — not a freshly re-converted
    price.usd × FX (the bug surfaced as "catalog shows 12 000 UZS but
    checkout shows 10 272.51 UZS"). The override skips the FX snapshot
    entirely; ``fx_snapshot_id`` stays NULL for an override-only order."""
    db_session.add(
        SkuPrice(
            sku_id=_seed_pubg["sku_id"],
            currency="UZS",
            price=Decimal("12000"),
        )
    )
    await db_session.commit()

    token = await _login_user(integration_client, tg_id=22)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "override-user22-aaaaaaaa",
        },
        json={
            "currency": "UZS",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "123456", "server": "as"},
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["currency"] == "UZS"
    assert Decimal(body["total_charged"]) == Decimal("12000")
    # USD remains the catalog's canonical price — used for margin /
    # cost reporting, even when the user paid native.
    assert Decimal(body["total_usd"]) == Decimal("0.85")
    # No FX snapshot needed since every line had an override.
    assert body["fx_snapshot_id"] is None


async def test_create_order_user_happy_path(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=12)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "user12-order-aaaaaaaaaaaa",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 2,
                    "fulfillment_data": {"player_id": "987654", "server": "eu"},
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending_payment"
    assert body["currency"] == "USD"
    assert Decimal(body["total_usd"]) == Decimal("1.70")
    assert Decimal(body["total_charged"]) == Decimal("1.70")
    assert body["fx_snapshot_id"] is None
    assert len(body["items"]) == 1
    assert body["items"][0]["qty"] == 2
    assert body["items"][0]["fulfillment_data"] == {"player_id": "987654", "server": "eu"}


async def test_create_order_idempotent_replay(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=13)
    payload = {
        "currency": "USD",
        "items": [
            {
                "sku_id": _seed_pubg["sku_id"],
                "qty": 1,
                "fulfillment_data": {"player_id": "123456", "server": "as"},
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "replay-key-bbbbbbbbbbbb",
    }
    r1 = await integration_client.post("/api/v1/orders", headers=headers, json=payload)
    r2 = await integration_client.post("/api/v1/orders", headers=headers, json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


async def test_create_order_missing_required_field(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=14)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "missing-field-cccccccccccc",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"server": "as"},  # no player_id
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "player_id" in r.text


async def test_create_order_pattern_violation(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=15)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "pattern-violation-dddddddd",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "abc", "server": "as"},
                }
            ],
        },
    )
    assert r.status_code == 422


async def test_create_order_unsupported_select_value(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=16)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "bad-select-eeeeeeeeeeee",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "123456", "server": "MARS"},
                }
            ],
        },
    )
    assert r.status_code == 422


# ---------- get / list ----------


async def test_get_order_only_owner(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    owner_token = await _login_user(integration_client, tg_id=21)
    other_token = await _login_user(integration_client, tg_id=22)
    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "Idempotency-Key": "owner-test-ffffffffffff",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "111111", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201
    order_id = create.json()["id"]

    # Owner can read.
    ok = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert ok.status_code == 200

    # Stranger gets 404.
    stranger = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert stranger.status_code == 404


async def test_paid_order_surfaces_payment_provider(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    """The customer order-detail view must show which provider the order was
    actually paid with — the newest succeeded payment's (normalized)
    provider slug, sourced from the eager-loaded ``Order.payments``."""
    token = await _login_user(integration_client, tg_id=61)
    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "provider-surface-iiiiiiii",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "222222", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]

    # Unpaid yet: no provider to surface.
    unpaid = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unpaid.status_code == 200, unpaid.text
    assert unpaid.json()["payment_provider"] is None

    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "provider-surface-intent-iiiiiiii",
        },
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code == 201, intent.text
    external_id = intent.json()["external_id"]

    wh = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": "evt_provider_surface_001",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text

    order_resp = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert order_resp.status_code == 200, order_resp.text
    body = order_resp.json()
    # The provider the customer actually paid with is surfaced (safe slug).
    assert body["payment_provider"] in {"click", "payme", "uzum", "octo", "wallet", "mock"}
    assert body["payment_provider"] == "mock"


async def _create_and_pay_order(client: AsyncClient, *, token: str, sku_id: str, key: str) -> str:
    """Create an order and pay it via the mock provider; returns the order id."""
    create = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]

    intent = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"{key}-intent"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code == 201, intent.text
    external_id = intent.json()["external_id"]

    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": f"evt_{key}", "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


async def test_orders_list_payment_provider_is_o1(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    sql_counter: dict[str, int],
) -> None:
    """Surfacing ``payment_provider`` on the orders list must not add a
    per-row query — ``Order.payments`` is ``lazy="raise"`` precisely so a
    missed ``selectinload`` fails loudly here instead of fanning out N+1 in
    production. The product SKU carries no fulfilment_data requirements, so
    the products used here need no ``required_fields``; a fresh product is
    used to keep the fixture minimal (it doesn't need the full brand/category
    seed the module-level ``_seed_pubg`` fixture builds for other tests)."""
    category = Category(id=new_id(), slug="qc-provider", sort_order=1, active=True)
    brand = Brand(
        id=new_id(), slug="qc-provider-brand", category_id=category.id, sort_order=1, active=True
    )
    product = Product(
        id=new_id(),
        slug="qc-provider-product",
        brand_id=brand.id,
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="qc-provider-sku",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()

    token = await _login_user(integration_client, tg_id=71)
    headers = {"Authorization": f"Bearer {token}"}

    order_id = await _create_and_pay_order(
        integration_client, token=token, sku_id=sku.id, key="qc-provider-order-01-pad"
    )
    await integration_client.get("/api/v1/orders", headers=headers)  # warm-up, untracked
    with_one = await _measure_get(integration_client, sql_counter, "/api/v1/orders", headers)

    order_ids = [order_id]
    for n in range(2, 6):
        order_ids.append(
            await _create_and_pay_order(
                integration_client,
                token=token,
                sku_id=sku.id,
                key=f"qc-provider-order-{n:02d}-pad",
            )
        )

    with_five = await _measure_get(integration_client, sql_counter, "/api/v1/orders", headers)
    assert with_five == with_one, (
        f"orders list with payment_provider grew from {with_one} to {with_five} queries "
        "— Order.payments is not being eager-loaded"
    )

    listed = (await integration_client.get("/api/v1/orders", headers=headers)).json()["items"]
    listed_by_id = {o["id"]: o for o in listed}
    for oid in order_ids:
        assert listed_by_id[oid]["payment_provider"] == "mock"


async def test_list_orders_for_user(
    integration_client: AsyncClient, _seed_pubg: dict[str, str]
) -> None:
    token = await _login_user(integration_client, tg_id=31)
    for i in range(3):
        r = await integration_client.post(
            "/api/v1/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"list-{i:02d}-gggggggggggg",
            },
            json={
                "currency": "USD",
                "items": [
                    {
                        "sku_id": _seed_pubg["sku_id"],
                        "qty": 1,
                        "fulfillment_data": {"player_id": "123456", "server": "as"},
                    }
                ],
            },
        )
        assert r.status_code == 201

    r = await integration_client.get("/api/v1/orders", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3


# ---------- admin ----------


async def test_admin_can_list_and_cancel(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    user_token = await _login_user(integration_client, tg_id=41)
    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Idempotency-Key": "admin-cancel-hhhhhhhhhhhh",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "555555", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201
    order_id = create.json()["id"]

    admin_token = await _login_user(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)

    listing = await integration_client.get(
        "/api/v1/admin/orders", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert listing.status_code == 200
    admin_order = next(o for o in listing.json()["items"] if o["id"] == order_id)
    # Admins keep the internal upstream supplier order id on each line — only
    # the customer-facing DTO strips it (see OrderItemOut vs OrderItemAdminOut).
    assert "supplier_order_id" in admin_order["items"][0]

    cancel = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    # A second cancel fails — order is not in pending_payment anymore.
    repeat = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert repeat.status_code == 409


async def test_admin_list_renders_order_with_reserved_tld_guest_email(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    """A guest email that is legal to store but fails strict RFC validation
    (reserved ``.local`` TLD, as seeded during Uzum sandbox payment testing)
    must render in the admin list rather than 500-ing the whole page. The
    admin output DTO carries ``guest_email`` as a plain ``str``, not
    ``EmailStr``, so it is not re-validated on the way out."""
    order = Order(
        id=new_id(),
        guest_email="uzum-test@test.local",
        status="pending_payment",
        currency="UZS",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("130000"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        items=[
            OrderItem(
                id=new_id(),
                sku_id=_seed_pubg["sku_id"],
                qty=1,
                unit_price_usd=Decimal("0.85"),
                fulfillment_data={"player_id": "555555", "server": "as"},
            )
        ],
    )
    db_session.add(order)
    await db_session.commit()

    admin_token = await _login_user(integration_client, tg_id=43)
    await _grant_admin(db_session, tg_id=43)

    listing = await integration_client.get(
        "/api/v1/admin/orders", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert listing.status_code == 200, listing.text
    match = [o for o in listing.json()["items"] if o["id"] == order.id]
    assert match, "seeded order missing from admin listing"
    assert match[0]["guest_email"] == "uzum-test@test.local"


async def test_admin_list_paginates_and_filters_by_date_range(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    """``limit``/``offset`` page the result and ``since``/``until`` narrow it
    to a ``created_at`` window — the filters admins reach for from the
    orders list page's date-range UI."""

    def _make_order(created_at: datetime) -> Order:
        return Order(
            id=new_id(),
            guest_email="daterange-test@example.com",
            status="pending_payment",
            currency="USD",
            total_usd=Decimal("1.00"),
            total_charged=Decimal("1.00"),
            expires_at=created_at + timedelta(hours=1),
            created_at=created_at,
            items=[
                OrderItem(
                    id=new_id(),
                    sku_id=_seed_pubg["sku_id"],
                    qty=1,
                    unit_price_usd=Decimal("0.85"),
                    fulfillment_data={"player_id": "555555", "server": "as"},
                )
            ],
        )

    now = datetime.now(UTC)
    old_order = _make_order(now - timedelta(days=10))
    mid_order = _make_order(now - timedelta(days=5))
    recent_order = _make_order(now - timedelta(hours=1))
    db_session.add_all([old_order, mid_order, recent_order])
    await db_session.commit()

    admin_token = await _login_user(integration_client, tg_id=44)
    await _grant_admin(db_session, tg_id=44)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # limit=1 pages down to a single row while total still reports every match.
    paged = await integration_client.get(
        "/api/v1/admin/orders",
        params={"limit": 1, "offset": 0},
        headers=headers,
    )
    assert paged.status_code == 200, paged.text
    assert len(paged.json()["items"]) == 1
    assert paged.json()["total"] >= 3

    # since/until narrows to the mid-range order only.
    windowed = await integration_client.get(
        "/api/v1/admin/orders",
        params={
            "since": (now - timedelta(days=7)).isoformat(),
            "until": (now - timedelta(days=2)).isoformat(),
        },
        headers=headers,
    )
    assert windowed.status_code == 200, windowed.text
    ids = {o["id"] for o in windowed.json()["items"]}
    assert mid_order.id in ids
    assert old_order.id not in ids
    assert recent_order.id not in ids


# ---------- expiry ----------


async def test_stale_order_lazy_expires_on_read(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    """Reading a ``pending_payment`` order past its ``expires_at`` should
    flip it to ``expired`` inline so the customer never stares at
    "ждём оплату · 4 days"."""
    from datetime import datetime, timedelta

    from yupay.modules.orders.models import Order

    token = await _login_user(integration_client, tg_id=51)
    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "expiry-lazy-aaaaaa",
        },
        json={
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "555555", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201
    order_id = create.json()["id"]

    # Wind the clock — back-date ``expires_at`` to 1 second ago.
    past = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.execute(update(Order).where(Order.id == order_id).values(expires_at=past))
    await db_session.commit()

    read = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "expired"
    assert body["cancelled_at"] is not None


async def test_expire_stale_orders_service_batch_flips_pending(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    """The scheduler job ``expire_stale_orders`` flips every TTL-exceeded
    ``pending_payment`` row and leaves healthy orders alone."""
    from datetime import datetime, timedelta

    from yupay.modules.orders import api as orders_api
    from yupay.modules.orders.models import Order

    token = await _login_user(integration_client, tg_id=52)

    # Two stale orders + one fresh.
    ids: list[str] = []
    for idx in range(3):
        r = await integration_client.post(
            "/api/v1/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"expiry-bulk-{idx:04d}-pad",
            },
            json={
                "items": [
                    {
                        "sku_id": _seed_pubg["sku_id"],
                        "qty": 1,
                        "fulfillment_data": {"player_id": "555555", "server": "as"},
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    stale_ids, fresh_id = ids[:2], ids[2]
    past = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.execute(update(Order).where(Order.id.in_(stale_ids)).values(expires_at=past))
    await db_session.commit()

    count = await orders_api.expire_stale_orders(db_session)
    await db_session.commit()
    assert count == 2

    for sid in stale_ids:
        r = await integration_client.get(
            f"/api/v1/orders/{sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "expired"

    r = await integration_client.get(
        f"/api/v1/orders/{fresh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending_payment"


async def test_admin_mark_failed_guards_and_cascades(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_pubg: dict[str, str],
) -> None:
    """Admin can close a paid-but-undeliverable order as ``failed``.

    The safe manual transition: it needs a reason, is refused before payment
    (that is ``cancel``) and after delivery (that is a refund — the customer
    already holds the goods), and it stops any in-flight fulfilment so a
    "failed" order can't still hand out codes.
    """
    user_token = await _login_user(integration_client, tg_id=71)
    admin_token = await _login_user(integration_client, tg_id=72)
    await _grant_admin(db_session, tg_id=72)
    admin_h = {"Authorization": f"Bearer {admin_token}"}

    create = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Idempotency-Key": "admin-fail-order-jjjjjjjjjj",
        },
        json={
            "currency": "USD",
            "items": [
                {
                    "sku_id": _seed_pubg["sku_id"],
                    "qty": 1,
                    "fulfillment_data": {"player_id": "777777", "server": "as"},
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]

    # Before payment the correct action is cancel, not fail.
    too_early = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/fail",
        headers=admin_h,
        json={"reason": "supplier outage"},
    )
    assert too_early.status_code == 409, too_early.text

    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Idempotency-Key": "admin-fail-intent-jjjjjjjjjj",
        },
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code == 201, intent.text
    wh = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": "evt_admin_fail_001",
                "payment_id": intent.json()["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text

    # A reason is mandatory — "who closed this and why" must be answerable.
    no_reason = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/fail", headers=admin_h, json={"reason": "  "}
    )
    assert no_reason.status_code == 422, no_reason.text

    failed = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/fail",
        headers=admin_h,
        json={"reason": "supplier can't deliver this SKU"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"

    # The reason is on the audit trail, attributed to the admin.
    detail = await integration_client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_h)
    events = detail.json()["events"]
    ev = next(e for e in events if e["kind"] == "order.failed")
    assert ev["payload"]["reason"] == "supplier can't deliver this SKU"
    assert ev["actor"].startswith("admin:")

    # No open fulfilment task survives a failed order. Assert a task actually
    # existed first — `all()` over an empty list would pass vacuously and prove
    # nothing about the cascade.
    tasks = await integration_client.get(
        f"/api/v1/admin/fulfillment/tasks?order_id={order_id}&limit=50", headers=admin_h
    )
    assert tasks.status_code == 200, tasks.text
    task_items = tasks.json()["items"]
    assert task_items, "payment should have started a fulfilment task to cascade over"
    assert all(t["status"] not in ("pending", "in_progress") for t in task_items)

    # Terminal already — repeating is refused rather than re-firing the cascade.
    repeat = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/fail", headers=admin_h, json={"reason": "again"}
    )
    assert repeat.status_code == 409, repeat.text
