"""Producing merchant webhook events into the outbox (M3a, Task 3).

The *producer* half of §10's webhooks: a row lands in
``merchant_webhook_deliveries`` **in the same transaction as the fact that
caused it**, and a ``pg_notify`` on ``merchant_webhook_queue`` rides that same
transaction so Postgres delivers it on COMMIT and drops it on ROLLBACK. Task 4
drains the table; nothing here delivers anything.

Four properties are asserted with the mechanism rather than a simulation of
it, because each is expensive to discover in production:

- **the payload's key set is exact.** Written as ``set(payload) == {...}``
  rather than "no key named ``code``": a voucher code is a bearer instrument
  and a webhook body is written to the receiver's logs wholesale (spec §10),
  so the assertion that has to hold is that *nothing new* can appear, not that
  one known name is absent.
- **rollback drops both the row and the NOTIFY**, checked against a real
  ``asyncpg`` listener on the channel, following
  ``test_fulfillment_async.test_notify_rides_the_transaction``.
- **a courtesy cannot fail money.** With the insert forced to raise, the order
  still commits and the deposit still moves.
- **retail is untouched.** A retail status change reaches
  ``realtime.publish_order_event`` with exactly the arguments it always did,
  and writes no delivery row.

``balance.credited`` gained a **second producer** in M3b Task 3 — the automatic
refund of a failed merchant order — and its payload is asserted with the same
exactness in ``test_merchant_auto_refund.py``, beside the code that emits it.
The event is unchanged: same two keys, same replay-announces-nothing rule.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle
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
from yupay.modules.merchants import webhooks as hooks
from yupay.modules.merchants.models import MerchantWebhook, MerchantWebhookDelivery
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ORDERS_PATH = "/merchant/v1/orders"
HOOK_URL = "https://hooks.reseller.example/yupay"
MOVED_URL = "https://hooks.reseller.example/yupay/v2"


# ---------- admin harness (shape shared with test_merchant_webhook_admin.py) ----------


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    tg_id = 3107
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _new_merchant(client: AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": "Reseller"})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _new_key(
    client: AsyncClient, headers: dict[str, str], merchant_id: str
) -> tuple[str, str]:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys",
        headers=headers,
        json={"label": "server"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    return payload["key_id"], payload["secret"]


async def _credit(
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    amount: str,
    key: str | None = None,
) -> Response:
    return await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": key or f"credit-{new_id()}"},
        json={"amount": amount},
    )


async def _set_hook(
    client: AsyncClient, headers: dict[str, str], merchant_id: str, url: str = HOOK_URL
) -> None:
    r = await client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=headers, json={"url": url}
    )
    assert r.status_code == 200, r.text


async def _disable_hook(client: AsyncClient, headers: dict[str, str], merchant_id: str) -> None:
    r = await client.delete(f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=headers)
    assert r.status_code == 200, r.text


def _signed(key_id: str, secret: str, *, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    message = "\n".join((ts, method.upper(), path, "", hashlib.sha256(body).hexdigest())).encode()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": hmac.new(
            secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }


async def _post_order(
    client: AsyncClient, key_id: str, secret: str, payload: dict[str, Any]
) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        ORDERS_PATH,
        content=body,
        headers=_signed(key_id, secret, method="POST", path=ORDERS_PATH, body=body),
    )


def _seed_sku(db: AsyncSession, *, n: int = 1) -> str:
    """One category → brand → product → SKU chain, b2b-visible, $1.00 at 7 %."""
    category = Category(
        id=new_id(),
        slug=f"cat-{n}-{new_id()[:8]}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}-{new_id()[:8]}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}-{new_id()[:8]}",
        brand_id=brand.id,
        kind="voucher",
        sort_order=n,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{n}-{new_id()[:8]}",
        denomination=f"{n}00 UC",
        region="GLOBAL",
        price_usd=Decimal("9.99"),
        cost_usdt=Decimal("1.000000"),
        visible_b2b=True,
        b2b_markup_pct=Decimal("7"),
        sort_order=0,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


async def _seeded(db: AsyncSession) -> str:
    sku_id = _seed_sku(db)
    await db.commit()
    return sku_id


async def _deliveries(db: AsyncSession, merchant_id: str) -> list[MerchantWebhookDelivery]:
    rows = (
        await db.execute(
            select(MerchantWebhookDelivery)
            .where(MerchantWebhookDelivery.merchant_id == merchant_id)
            .order_by(MerchantWebhookDelivery.created_at, MerchantWebhookDelivery.id)
        )
    ).scalars()
    return list(rows)


async def _pilot(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession, *, hook: bool = True
) -> tuple[str, str, str, str]:
    """A merchant with a key, $10 of deposit, an optional hook, and a SKU."""
    merchant_id = await _new_merchant(client, headers)
    key_id, secret = await _new_key(client, headers, merchant_id)
    r = await _credit(client, headers, merchant_id, "10.00")
    assert r.status_code == 201, r.text
    if hook:
        await _set_hook(client, headers, merchant_id)
    sku_id = await _seeded(db)
    return merchant_id, key_id, secret, sku_id


# ---------- order.status_changed ----------


async def test_a_merchant_order_enqueues_paid_and_fulfilling_with_an_exact_payload(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Born ``paid``, planned into ``fulfilling`` — one delivery each, and the
    payload's key set is exactly the contract's four."""
    merchant_id, key_id, secret, sku_id = await _pilot(
        integration_client, admin_headers, db_session
    )
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]

    rows = await _deliveries(db_session, merchant_id)
    assert [row.event_type for row in rows] == ["order.status_changed"] * 2
    assert [row.payload["status"] for row in rows] == ["paid", "fulfilling"]
    for row in rows:
        assert set(row.payload) == {"merchant_order_id", "order_id", "status", "at"}
        assert row.payload["merchant_order_id"] == "evt-1"
        assert row.payload["order_id"] == order_id
        assert row.payload["at"].endswith("+00:00")
        assert row.status == "pending"
        assert row.attempts_count == 0
        assert row.url == HOOK_URL


async def test_delivering_the_order_enqueues_delivered_and_never_the_code(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The event a reseller actually waits for — and the bearer instrument it
    must not carry. Asserted twice over: the key set is exact, and the issued
    code does not appear anywhere in any payload we enqueued."""
    merchant_id, key_id, secret, sku_id = await _pilot(
        integration_client, admin_headers, db_session
    )
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-2", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]

    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    order = await db_session.get(Order, order_id)
    assert order is not None
    assert order.status == "delivered"

    rows = await _deliveries(db_session, merchant_id)
    assert [row.payload["status"] for row in rows] == ["paid", "fulfilling", "delivered"]
    for row in rows:
        assert set(row.payload) == {"merchant_order_id", "order_id", "status", "at"}

    artifacts = await ff_svc.list_deliveries_for_order(db_session, order_id=order_id)
    assert artifacts, "the fixture must actually issue an artifact or this proves nothing"
    secrets = [
        value
        for artifact in artifacts
        for value in (artifact.artifact or {}).values()
        if isinstance(value, str) and value
    ]
    assert secrets, "the artifact must carry at least one string or this proves nothing"
    blob = json.dumps([row.payload for row in rows])
    for value in secrets:
        assert value not in blob


async def test_no_webhook_configured_enqueues_nothing(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The outbox holds only deliverable work — never a row Task 4 must skip."""
    merchant_id, key_id, secret, sku_id = await _pilot(
        integration_client, admin_headers, db_session, hook=False
    )
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-3", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    assert await _deliveries(db_session, merchant_id) == []


async def test_a_disabled_webhook_enqueues_nothing(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Disabled and absent are the same outcome: no row."""
    merchant_id, key_id, secret, sku_id = await _pilot(
        integration_client, admin_headers, db_session
    )
    await _disable_hook(integration_client, admin_headers, merchant_id)
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-4", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    assert await _deliveries(db_session, merchant_id) == []


async def test_the_url_is_snapshotted_at_enqueue_and_a_later_move_does_not_rewrite_it(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Moving the endpoint must not re-attribute yesterday's deliveries."""
    merchant_id, key_id, secret, sku_id = await _pilot(
        integration_client, admin_headers, db_session
    )
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-5", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text

    await _set_hook(integration_client, admin_headers, merchant_id, MOVED_URL)

    rows = await _deliveries(db_session, merchant_id)
    assert rows
    assert {row.url for row in rows} == {HOOK_URL}


# ---------- the NOTIFY rides the transaction ----------


async def _merchant_order_row(db: AsyncSession, merchant_id: str, *, tag: str) -> Order:
    order = Order(
        id=new_id(),
        merchant_id=merchant_id,
        idempotency_key=tag,
        status="paid",
        purpose="catalog",
        currency="USD",
        total_usd=Decimal("1.07"),
        total_charged=Decimal("1.07"),
        source="unknown",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(order)
    await db.flush()
    return order


async def test_a_rolled_back_transaction_leaves_no_row_and_fires_no_notify(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Both halves of the outbox ride the caller's transaction — asserted with
    a real listener, not a mock."""
    from yupay.modules.orders import service as orders_svc

    merchant_id = await _new_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)

    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    heard: list[str] = []
    await conn.add_listener(hooks.WEBHOOK_QUEUE_CHANNEL, lambda *a: heard.append(a[-1]))
    try:
        rolled = await _merchant_order_row(db_session, merchant_id, tag="rb")
        rolled_delivery = await orders_svc.on_order_status_changed(db_session, rolled)
        assert rolled_delivery is not None
        await db_session.rollback()
        await asyncio.sleep(0.2)
        # Asserting on this delivery's own id rather than an empty list keeps
        # the check immune to any cross-test chatter on the same channel.
        assert rolled_delivery not in heard
        assert await _deliveries(db_session, merchant_id) == []

        kept = await _merchant_order_row(db_session, merchant_id, tag="ok")
        kept_delivery = await orders_svc.on_order_status_changed(db_session, kept)
        assert kept_delivery is not None
        await db_session.commit()
        await asyncio.sleep(0.2)
        assert kept_delivery in heard
        assert [row.id for row in await _deliveries(db_session, merchant_id)] == [kept_delivery]
    finally:
        await conn.close()


# ---------- a courtesy cannot fail money ----------


class _SpyLog:
    """Stands in for the module logger; records the ``error`` calls."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, dict[str, Any]]] = []

    def error(self, event: str, **kwargs: Any) -> None:
        self.errors.append((event, kwargs))


async def test_an_enqueue_that_raises_does_not_roll_back_the_order(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An order is money; a webhook is a courtesy. With the delivery insert
    forced into a primary-key violation, the order still commits, the deposit
    still moved, and ops gets a loud line."""
    merchant_id, key_id, secret, sku_id = await _pilot(
        integration_client, admin_headers, db_session
    )
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-6a", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    already = [row.id for row in await _deliveries(db_session, merchant_id)]
    assert len(already) == 2

    spy = _SpyLog()
    monkeypatch.setattr(hooks, "log", spy)
    monkeypatch.setattr(hooks, "new_id", lambda: already[0])

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "evt-6b", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["balance_usd"] == "7.86"  # 10.00 - 1.07 - 1.07: the money moved

    order = await db_session.get(Order, body["order_id"])
    assert order is not None
    assert order.status == "fulfilling"
    # Nothing new in the outbox, and the failure was reported rather than
    # swallowed in silence.
    assert [row.id for row in await _deliveries(db_session, merchant_id)] == already
    assert [event for event, _ in spy.errors] == [
        "merchant_webhook.enqueue_failed",
        "merchant_webhook.enqueue_failed",
    ]
    fields = spy.errors[0][1]
    assert fields["order_id"] == body["order_id"]
    assert fields["merchant_id"] == merchant_id
    assert fields["event_type"] == "order.status_changed"
    assert fields["failure"] == "IntegrityError"
    assert fields["sqlstate"] == "23505"  # unique_violation
    # And nothing else. The driver's own message is deliberately absent: a
    # NotNullViolation renders ``DETAIL: Failing row contains (…)``, which
    # would put the ``url`` snapshot -- sized to hold a path with a token in
    # it -- into the log over a courtesy failure.
    assert set(fields) == {
        "merchant_id",
        "event_type",
        "delivery_id",
        "order_id",
        "failure",
        "sqlstate",
    }


# ---------- balance.credited ----------


async def test_crediting_the_deposit_enqueues_the_amount_and_the_new_balance(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Money as strings, two decimals, exactly two keys."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)

    assert (await _credit(integration_client, admin_headers, merchant_id, "10.00")).status_code
    assert (await _credit(integration_client, admin_headers, merchant_id, "5.50")).status_code

    rows = await _deliveries(db_session, merchant_id)
    assert [row.event_type for row in rows] == ["balance.credited"] * 2
    assert [row.payload for row in rows] == [
        {"amount_usd": "10.00", "balance_usd": "10.00"},
        {"amount_usd": "5.50", "balance_usd": "15.50"},
    ]


async def test_a_replayed_credit_enqueues_nothing_the_second_time(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The ledger replays by key and books nothing; the webhook must not
    announce a credit that did not happen."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)

    key = f"same-{new_id()}"
    assert (
        await _credit(integration_client, admin_headers, merchant_id, "4.00", key=key)
    ).status_code == 201
    assert (
        await _credit(integration_client, admin_headers, merchant_id, "4.00", key=key)
    ).status_code == 201

    rows = await _deliveries(db_session, merchant_id)
    assert [row.payload for row in rows] == [{"amount_usd": "4.00", "balance_usd": "4.00"}]


# ---------- retail is untouched ----------


async def test_a_retail_status_change_still_nudges_realtime_with_the_same_arguments(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam must be invisible to the storefront: same call, same payload,
    and no delivery row anywhere."""
    from yupay.modules.orders import service as orders_svc
    from yupay.modules.realtime import api as realtime

    calls: list[tuple[Any, ...]] = []

    async def _spy(*args: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(realtime, "publish_order_event", _spy)

    user_id = new_id()
    db_session.add(
        User(
            id=user_id,
            email=f"retail-{user_id[:8]}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db_session.flush()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="pending_payment",
        purpose="catalog",
        currency="UZS",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("12000"),
        source="web",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(order)
    await db_session.flush()

    before = (await db_session.execute(select(MerchantWebhookDelivery.id))).scalars().all()

    order.status = "cancelled"
    order.updated_at = order.created_at
    await orders_svc.on_order_status_changed(db_session, order)

    assert calls == [
        (
            user_id,
            {
                "type": "order.status_changed",
                "orderId": order.id,
                "status": "cancelled",
                "at": order.updated_at.isoformat(),
            },
        )
    ]
    after = (await db_session.execute(select(MerchantWebhookDelivery.id))).scalars().all()
    assert list(after) == list(before)


async def test_a_retail_delivery_still_publishes_only_order_delivered(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settle path routes through the seam for its webhook half only.

    A connected storefront receives ``order.delivered`` and nothing else, as
    it always has — the seam must not start sending it a second
    ``order.status_changed`` for the same transition.
    """
    from yupay.modules.realtime import api as realtime

    published: list[dict[str, Any]] = []

    async def _spy(_user_id: str | None, event: dict[str, Any]) -> None:
        published.append(event)

    monkeypatch.setattr(realtime, "publish_order_event", _spy)

    user_id = new_id()
    db_session.add(
        User(
            id=user_id,
            email=f"settle-{user_id[:8]}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    sku_id = _seed_sku(db_session, n=7)
    await db_session.flush()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="paid",
        purpose="catalog",
        currency="UZS",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("12000"),
        source="web",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("1.00"),
            fulfillment_data={},
        )
    )
    await db_session.commit()

    await ff_svc.start_for_order(db_session, order_id=order.id)
    await db_session.commit()

    refreshed = await db_session.get(Order, order.id)
    assert refreshed is not None
    assert refreshed.status == "delivered"
    assert [event["type"] for event in published] == [
        "order.status_changed",  # paid -> fulfilling
        "order.delivered",
    ]


async def test_the_channel_name_is_the_one_task_four_listens_on() -> None:
    """One constant, one string — a mismatch here is a queue nobody drains."""
    assert hooks.WEBHOOK_QUEUE_CHANNEL == "merchant_webhook_queue"


async def test_an_unknown_event_type_is_refused_at_the_boundary(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``event_type`` carries no DB CHECK on purpose; the vocabulary is kept
    here instead, so a third event is a code change and not a migration."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)
    with pytest.raises(ValueError, match="unknown merchant webhook event"):
        await hooks.enqueue(
            db_session, merchant_id=merchant_id, event_type="order.exploded", payload={}
        )


async def test_a_hook_belongs_to_one_merchant_only(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A configured hook must never collect another merchant's events."""
    listener = await _new_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, listener)
    quiet = await _new_merchant(integration_client, admin_headers)

    assert (await _credit(integration_client, admin_headers, quiet, "3.00")).status_code == 201

    assert await _deliveries(db_session, quiet) == []
    assert await _deliveries(db_session, listener) == []
    rows = (
        (
            await db_session.execute(
                select(MerchantWebhook).where(MerchantWebhook.merchant_id == quiet)
            )
        )
        .scalars()
        .all()
    )
    assert list(rows) == []
