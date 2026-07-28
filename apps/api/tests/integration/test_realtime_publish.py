"""Integration tests for realtime publishing at order-status transitions.

Task 2 of the order-realtime-ws plan: every order-status transition wired in
``payments``/``fulfillment``/``orders`` must publish to the owning user's
``realtime:user:{uid}`` Redis channel. These tests drive the transitions
through the real HTTP + service layers (reusing the login/order/pay helpers
from ``test_inventory_sourcing_routes.py`` / ``test_fulfillment_service_paths.py``)
and verify the message lands via a genuine dev-Redis SUBSCRIBE — a brand-new
``redis.asyncio`` connection, never the app's cached ``get_redis()`` singleton,
to avoid the "Future attached to a different loop" trap noted in
``test_realtime_ws.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any, NoReturn
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis, from_url
from redis.asyncio.client import PubSub
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle
from yupay.core.clock import now
from yupay.core.config import get_settings
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
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.inventory import service as inv_svc
from yupay.modules.orders import service as orders_svc
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


# ---------- login / order / pay helpers (mirrors the other fulfilment integration tests) ----------


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
    return str(r.json()["access_token"])


async def _user_id_for_tg(db: AsyncSession, tg_id: int) -> str:
    return str(
        (
            await db.execute(
                select(User.id)
                .join(TelegramLink, TelegramLink.user_id == User.id)
                .where(TelegramLink.tg_user_id == tg_id)
            )
        ).scalar_one()
    )


def _seed_sku(db: AsyncSession, *, slug: str, kind: str = "voucher") -> str:
    """A brand/product/sku triple. ``kind='voucher'`` (the default here) routes
    inventory-first with no sourcing rule, matching ``test_inventory_sourcing_routes.py``."""
    category = Category(
        id=new_id(),
        slug=f"cat-{slug}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=slug)],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{slug}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name=slug)],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{slug}",
        brand_id=brand.id,
        kind=kind,
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug)],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{slug}",
        denomination="10",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


async def _order(client: AsyncClient, *, token: str, sku_id: str, tag: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"rt-order-{tag}-pad"},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _pay(client: AsyncClient, *, token: str, order_id: str, tag: str) -> None:
    r = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"rt-intent-{tag}-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"rt_{tag}",
                "payment_id": r.json()["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text


# ---------- real Redis pub/sub helpers ----------


async def _subscribe(redis: Redis, channel: str) -> PubSub:
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    await pubsub.get_message(timeout=5)  # drain the "subscribe" confirmation frame
    return pubsub


async def _collect(pubsub: PubSub, *, count: int, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Collect up to ``count`` published JSON messages, or give up at ``timeout``."""
    messages: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while len(messages) < count:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        msg = await pubsub.get_message(timeout=remaining)
        if msg is not None and msg.get("type") == "message":
            messages.append(json.loads(msg["data"]))
    return messages


@pytest.fixture
async def redis_client() -> Any:
    """A dedicated Redis connection for the test's own SUBSCRIBE, separate from
    the app's cached ``get_redis()`` singleton (which ``publish_order_event``
    uses on the *publish* side).

    Also resets that singleton around the test: each pytest-asyncio test runs
    on its own event loop, and a client cached from a previous test (or left
    behind by a service call that doesn't go through the ``integration_client``
    fixture, e.g. ``orders_svc``/``ff_svc`` called directly against
    ``db_session``) would otherwise raise "Future attached to a different
    loop" the moment this test's code path calls ``get_redis()``.
    """
    from yupay.core import redis as core_redis

    core_redis._client = None
    client = from_url(get_settings().redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
        await core_redis.close_redis()


# ---------- tests ----------


async def test_paid_fulfilling_and_delivered_publish(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """Paying an order that the warehouse can serve immediately fires
    ``paid`` → ``fulfilling`` → ``delivered``, each landing on the customer's
    realtime channel."""
    sku_id = _seed_sku(db_session, slug="rt-deliv")
    await db_session.commit()
    await inv_svc.bulk_upload(db_session, sku_id=sku_id, codes=["RT-STOCK-1"], uploaded_by="test")
    await db_session.commit()

    token = await _login_user(integration_client, tg_id=88001)
    uid = await _user_id_for_tg(db_session, tg_id=88001)

    pubsub = await _subscribe(redis_client, f"realtime:user:{uid}")
    try:
        order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="deliv")
        await _pay(integration_client, token=token, order_id=order_id, tag="deliv")
        messages = await _collect(pubsub, count=3, timeout=5)
    finally:
        await pubsub.unsubscribe(f"realtime:user:{uid}")
        await pubsub.aclose()  # type: ignore[no-untyped-call]

    delivered = [m for m in messages if m["type"] == "order.delivered"]
    assert len(delivered) == 1, messages
    assert delivered[0]["orderId"] == order_id
    assert delivered[0]["payload"] == {"kind": "order", "data": None}

    status_changed = [m for m in messages if m["type"] == "order.status_changed"]
    assert any(m["status"] == "paid" and m["orderId"] == order_id for m in status_changed)
    assert any(m["status"] == "fulfilling" and m["orderId"] == order_id for m in status_changed)


async def test_task_failure_does_not_publish_order_failed(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """DOMAIN RULE: a fulfilment failure is not an order failure.

    A SKU force-routed to an unintegrated supplier stub fails its task
    synchronously (``FulfillerNotIntegratedError``), but the order must stay
    ``fulfilling`` — no ``order.failed`` is ever published. Only the two
    expected ``status_changed`` events (``paid``, ``fulfilling``) land; the
    admin resolves the stuck task out-of-band (retry or manual completion)."""
    sku_id = _seed_sku(db_session, slug="rt-fail")
    await db_session.commit()
    db_session.add(SkuSourcingRule(sku_id=sku_id, mode="force_supplier", supplier_slug="steam"))
    await db_session.commit()

    token = await _login_user(integration_client, tg_id=88002)
    uid = await _user_id_for_tg(db_session, tg_id=88002)

    pubsub = await _subscribe(redis_client, f"realtime:user:{uid}")
    try:
        order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="fail")
        await _pay(integration_client, token=token, order_id=order_id, tag="fail")
        messages = await _collect(pubsub, count=2, timeout=5)
        # Give any (incorrect) extra publish a chance to land before asserting
        # its absence — collect() above already stops as soon as it has 2.
        extra = await pubsub.get_message(timeout=1)
    finally:
        await pubsub.unsubscribe(f"realtime:user:{uid}")
        await pubsub.aclose()  # type: ignore[no-untyped-call]

    assert extra is None, extra
    assert not any(m["type"] == "order.failed" for m in messages), messages

    status_changed = [m for m in messages if m["type"] == "order.status_changed"]
    assert any(m["status"] == "paid" and m["orderId"] == order_id for m in status_changed)
    assert any(m["status"] == "fulfilling" and m["orderId"] == order_id for m in status_changed)

    refreshed = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert refreshed.status == "fulfilling"


async def test_guest_order_publishes_nothing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guest order (``user_id=None``) must reach ``delivered`` without ever
    touching Redis — ``publish_order_event`` no-ops before calling ``get_redis()``."""
    import yupay.modules.realtime.service as realtime_service

    def _must_not_call_redis() -> NoReturn:
        raise AssertionError("a guest order must never touch Redis")

    monkeypatch.setattr(realtime_service, "get_redis", _must_not_call_redis)

    sku_id = _seed_sku(db_session, slug="rt-guest")
    await db_session.commit()
    await inv_svc.bulk_upload(
        db_session, sku_id=sku_id, codes=["RT-STOCK-GUEST"], uploaded_by="test"
    )
    await db_session.commit()

    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="guest-rt@example.com",
        status="paid",
        currency="USD",
        total_usd=Decimal("1.50"),
        total_charged=Decimal("1.50"),
        expires_at=now() + timedelta(hours=1),
    )
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=Decimal("1.50"),
    )
    db_session.add_all([order, item])
    await db_session.commit()

    await ff_svc.start_for_order(db_session, order_id=order.id)
    await db_session.commit()

    refreshed = (await db_session.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert refreshed.status == "delivered"


async def test_cancel_publishes_status_changed(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """Admin-cancelling a ``pending_payment`` order publishes ``order.status_changed``
    with ``status: "cancelled"``."""
    user_id = new_id()
    db_session.add(User(id=user_id, roles=[]))
    await db_session.flush()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="pending_payment",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        expires_at=now() + timedelta(hours=1),
    )
    db_session.add(order)
    await db_session.commit()

    pubsub = await _subscribe(redis_client, f"realtime:user:{user_id}")
    try:
        await orders_svc.cancel_order_admin(db_session, order.id, admin_id="admin-rt")
        await db_session.commit()
        messages = await _collect(pubsub, count=1, timeout=5)
    finally:
        await pubsub.unsubscribe(f"realtime:user:{user_id}")
        await pubsub.aclose()  # type: ignore[no-untyped-call]

    assert len(messages) == 1, messages
    assert messages[0]["type"] == "order.status_changed"
    assert messages[0]["status"] == "cancelled"
    assert messages[0]["orderId"] == order.id


async def test_expire_publishes_status_changed(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """A ``pending_payment`` order past its TTL publishes ``order.status_changed``
    with ``status: "expired"`` when the scheduler sweep flips it."""
    user_id = new_id()
    db_session.add(User(id=user_id, roles=[]))
    await db_session.flush()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="pending_payment",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        expires_at=now() - timedelta(minutes=1),
    )
    db_session.add(order)
    await db_session.commit()

    pubsub = await _subscribe(redis_client, f"realtime:user:{user_id}")
    try:
        flipped = await orders_svc.expire_stale_orders(db_session)
        await db_session.commit()
        messages = await _collect(pubsub, count=1, timeout=5)
    finally:
        await pubsub.unsubscribe(f"realtime:user:{user_id}")
        await pubsub.aclose()  # type: ignore[no-untyped-call]

    assert flipped == 1
    assert len(messages) == 1, messages
    assert messages[0]["type"] == "order.status_changed"
    assert messages[0]["status"] == "expired"
    assert messages[0]["orderId"] == order.id
