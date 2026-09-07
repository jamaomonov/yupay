"""``GET /merchant/v1/orders/{merchant_order_id}`` — the reseller's order read (M2, Task 5).

Where a reseller collects the goods. M3's webhook will not carry the voucher
code, so this endpoint is the *only* place a delivered artifact reaches the
merchant, and two properties are load-bearing:

* **Scope.** The order is found by the *authenticated* merchant plus their own
  id — never by a path parameter naming a merchant — and merchant B asking for
  merchant A's order gets the same 404 as a nonexistent one.
* **Encoding.** ``merchant_order_id`` is ``^[\\x21-\\x7e]+$``, which includes
  ``/``. The path segment is percent-decoded before it is matched, and the
  signature covers the *encoded* request line. Both directions are pinned
  below.

The signature is rebuilt by hand from the module README rather than imported
from ``merchants.signing`` — same reason as the sibling read tests: a test that
calls the implementation it is testing proves only that it is deterministic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
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
from yupay.modules.fulfillment.models import Delivery, FulfillmentTask
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ORDERS_PATH = "/merchant/v1/orders"


# ---------- harness ----------


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
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 93, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 93)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _new_merchant(
    client: AsyncClient, headers: dict[str, str], title: str = "Reseller"
) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
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
    client: AsyncClient, headers: dict[str, str], merchant_id: str, amount: str
) -> None:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": amount},
    )
    assert r.status_code == 201, r.text


def _signed(
    key_id: str, secret: str, *, method: str, path: str, query: str = "", body: bytes = b""
) -> dict[str, str]:
    """The three auth headers, transcribed from the module README by hand.

    ``path`` is the **raw** request-line path: percent-encoded, exactly the
    bytes that go on the wire.
    """
    ts = str(int(time.time()))
    message = "\n".join(
        (ts, method.upper(), path, query, hashlib.sha256(body).hexdigest())
    ).encode()
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


def _read_path(merchant_order_id: str) -> str:
    """The raw request-line path for an id, percent-encoding every reserved byte.

    ``safe=""`` on purpose: ``/`` is legal inside a ``merchant_order_id`` and
    must travel as ``%2F``, which is the whole point of this endpoint's
    routing.
    """
    return f"{ORDERS_PATH}/{quote(merchant_order_id, safe='')}"


async def _read(client: AsyncClient, key_id: str, secret: str, merchant_order_id: str) -> Response:
    path = _read_path(merchant_order_id)
    return await client.get(path, headers=_signed(key_id, secret, method="GET", path=path))


# ---------- seeding ----------


def _seed_sku(db: AsyncSession, *, n: int = 1) -> str:
    """One category → brand → product → SKU chain at $1.00 cost / 7% markup."""
    category = Category(
        id=new_id(),
        slug=f"cat-{n}-{new_id()[-8:]}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}-{new_id()[-8:]}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}-{new_id()[-8:]}",
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
        sku_code=f"sku-{n}-{new_id()[-8:]}",
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


async def _seeded(db: AsyncSession, **kwargs: Any) -> str:
    sku_id = _seed_sku(db, **kwargs)
    await db.commit()
    return sku_id


async def _place(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    *,
    merchant_order_id: str,
    title: str = "Reseller",
) -> tuple[str, str, str, str]:
    """Fully set up a merchant, key, deposit and one placed order.

    Returns ``(merchant_id, key_id, secret, order_id)``.
    """
    merchant_id = await _new_merchant(client, headers, title=title)
    key_id, secret = await _new_key(client, headers, merchant_id)
    await _credit(client, headers, merchant_id, "10.00")
    sku_id = await _seeded(db)
    r = await _post_order(
        client,
        key_id,
        secret,
        {"merchant_order_id": merchant_order_id, "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    return merchant_id, key_id, secret, r.json()["order_id"]


async def _deliver(db: AsyncSession, order_id: str, *, artifact: dict[str, Any]) -> None:
    """Walk one order to ``delivered`` by hand, with a delivery artifact on it.

    The saga is ``fulfillment``'s and is tested there; a merchant order's
    fulfilment is always *enqueued*, so nothing runs inside the request that
    placed it. What is under test here is the projection, so the end state is
    written directly rather than drained through a worker.
    """
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order_id))).scalar_one()
    task = (
        await db.execute(select(FulfillmentTask).where(FulfillmentTask.order_id == order_id))
    ).scalar_one()
    task.status = "succeeded"
    item.fulfillment_state = "delivered"
    order.status = "delivered"
    order.fulfilled_at = order.created_at
    order.delivered_at = order.created_at
    db.add(
        Delivery(
            id=new_id(),
            order_item_id=item.id,
            channel="in_app",
            artifact_kind="voucher_code",
            artifact=artifact,
        )
    )
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="order.delivered",
            payload={"tasks": [task.id]},
            actor="fulfillment",
        )
    )
    await db.commit()


def _no_floats(raw: str) -> object:
    """``json.loads`` hook that refuses any JSON number — money is a string."""
    raise AssertionError(f"money must be a JSON string, got the number {raw}")


# ---------- the happy path ----------


async def test_reading_back_a_placed_order_returns_its_status_and_price(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-1"
    )

    r = await _read(integration_client, key_id, secret, "acme-1")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merchant_order_id"] == "acme-1"
    assert body["order_id"] == order_id
    assert body["status"] == "fulfilling"
    assert body["price_usd"] == "1.07"
    assert body["refunded_usd"] == "0.00"
    assert body["failure_reason"] is None
    assert body["delivery"] is None
    assert body["delivered_at"] is None
    assert body["paid_at"] is not None


async def test_money_leaves_this_endpoint_as_a_string_never_a_float(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, key_id, secret, _ = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-float"
    )

    r = await _read(integration_client, key_id, secret, "acme-float")

    assert r.status_code == 200, r.text
    # Blows up on any JSON number anywhere in the body.
    json.loads(r.text, parse_float=_no_floats, parse_int=_no_floats)


# ---------- the encoding trap ----------


async def test_an_order_id_containing_a_slash_routes_and_matches(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``merchant_order_id``'s pattern includes ``/`` (0x2F).

    The README's own worked example is ``/merchant/v1/orders/my%2Forder``. A
    route that split the path on ``/`` would 404 every such order — and would
    do it only for the resellers whose numbering happens to use a slash, which
    is the kind of bug that ships.
    """
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme/2026/000417"
    )

    path = _read_path("acme/2026/000417")
    assert path == "/merchant/v1/orders/acme%2F2026%2F000417"
    r = await integration_client.get(path, headers=_signed(key_id, secret, method="GET", path=path))

    assert r.status_code == 200, r.text
    assert r.json()["merchant_order_id"] == "acme/2026/000417"
    assert r.json()["order_id"] == order_id


async def test_an_order_id_containing_a_percent_sign_round_trips(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``%`` must survive one round of percent-decoding, not two."""
    _, key_id, secret, _ = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="100%-off"
    )

    path = _read_path("100%-off")
    assert path == "/merchant/v1/orders/100%25-off"
    r = await integration_client.get(path, headers=_signed(key_id, secret, method="GET", path=path))

    assert r.status_code == 200, r.text
    assert r.json()["merchant_order_id"] == "100%-off"


async def test_the_signature_covers_the_encoded_path_not_the_decoded_one(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Task 2's canonical string signs the request line, so ``%2F`` is signed as ``%2F``.

    A client that decodes before signing produces a valid-looking signature
    over the wrong bytes and must get a 401, not a 200 — otherwise the two
    spellings of one path would both verify and the encoding would stop being
    covered at all.
    """
    _, key_id, secret, _ = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme/slash"
    )

    path = _read_path("acme/slash")
    decoded = "/merchant/v1/orders/acme/slash"
    r = await integration_client.get(
        path, headers=_signed(key_id, secret, method="GET", path=decoded)
    )

    assert r.status_code == 401, r.text
    assert r.json()["code"] == "invalid_credentials"


# ---------- cross-merchant isolation ----------


async def test_merchant_b_cannot_read_merchant_as_order_and_cannot_tell_it_exists(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The security property of this task: no oracle for "not yours" vs "not found".

    Both answers must be byte-identical — a distinguishable 403 would let a
    reseller enumerate a competitor's order numbering.
    """
    await _place(integration_client, admin_headers, db_session, merchant_order_id="a-secret-1")
    other_id = await _new_merchant(integration_client, admin_headers, title="Merchant B")
    b_key, b_secret = await _new_key(integration_client, admin_headers, other_id)

    theirs = await _read(integration_client, b_key, b_secret, "a-secret-1")
    nonexistent = await _read(integration_client, b_key, b_secret, "never-existed")

    assert theirs.status_code == 404, theirs.text
    assert nonexistent.status_code == 404, nonexistent.text
    assert theirs.json() == nonexistent.json()
    assert theirs.json()["code"] == "order_not_found"


async def test_two_merchants_may_use_the_same_order_id_and_each_reads_their_own(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Scope is per account — the id space is the reseller's, not ours."""
    _, a_key, a_secret, a_order = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="shared-id", title="A"
    )
    _, b_key, b_secret, b_order = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="shared-id", title="B"
    )
    assert a_order != b_order

    a = await _read(integration_client, a_key, a_secret, "shared-id")
    b = await _read(integration_client, b_key, b_secret, "shared-id")

    assert a.json()["order_id"] == a_order
    assert b.json()["order_id"] == b_order


async def test_an_unknown_order_id_is_a_documented_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    r = await _read(integration_client, key_id, secret, "no-such-order")

    assert r.status_code == 404, r.text
    body = r.json()
    assert body["code"] == "order_not_found"
    assert body["type"] == "https://app.yupay.uz/errors/not-found"


async def test_an_empty_order_id_is_the_same_404_not_a_crash(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """``GET /merchant/v1/orders/`` matches the route with an empty segment."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    path = f"{ORDERS_PATH}/"
    r = await integration_client.get(path, headers=_signed(key_id, secret, method="GET", path=path))

    assert r.status_code == 404, r.text
    assert r.json()["code"] == "order_not_found"


# ---------- the delivered artifact ----------


async def test_the_delivered_voucher_code_comes_back_on_this_endpoint(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """M3's webhook will not carry the code; this is where a reseller collects it."""
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-delivered"
    )
    await _deliver(db_session, order_id, artifact={"code": "WXYZ-1234-ABCD"})

    r = await _read(integration_client, key_id, secret, "acme-delivered")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "delivered"
    assert body["delivered_at"] is not None
    assert body["delivery"]["artifact_kind"] == "voucher_code"
    assert body["delivery"]["artifact"] == {"code": "WXYZ-1234-ABCD"}


async def test_internal_artifact_fields_never_reach_a_reseller(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The artifact allow-list is ``fulfillment``'s, shared rather than copied.

    ``source``, ``inventory_code_id`` and ``external_order_id`` name our
    upstream supplier and our warehouse row. A reseller reconciling against
    them would be reconciling against our cost base.
    """
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-internal"
    )
    await _deliver(
        db_session,
        order_id,
        artifact={
            "code": "SAFE-CODE",
            "source": "g2b",
            "inventory_code_id": new_id(),
            "external_order_id": "supplier-99",
            "catalogue_name": "internal name",
        },
    )

    r = await _read(integration_client, key_id, secret, "acme-internal")

    assert r.status_code == 200, r.text
    assert r.json()["delivery"]["artifact"] == {"code": "SAFE-CODE"}
    for leaked in ("g2b", "supplier-99", "internal name"):
        assert leaked not in r.text


# ---------- timeline ----------


async def test_the_timeline_carries_the_order_lifecycle_and_nothing_else(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """An allow-list, not a dump: ``order_events`` also holds internal audit rows.

    ``admin.deliveries_viewed`` records which operator read a customer's codes.
    A reseller has no business seeing it, and a new internal event kind must
    default to hidden.
    """
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-timeline"
    )
    db_session.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="admin.deliveries_viewed",
            payload={"count": 1},
            actor="admin:someone",
        )
    )
    await db_session.commit()

    r = await _read(integration_client, key_id, secret, "acme-timeline")

    assert r.status_code == 200, r.text
    events = [e["event"] for e in r.json()["timeline"]]
    assert events == ["order.created", "order.paid", "order.fulfilling"]
    assert all(set(e) == {"event", "at"} for e in r.json()["timeline"])


async def test_the_timeline_carries_no_event_payloads(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``order.paid``'s payload holds the replay digest of the request body.

    It is a fingerprint of the reseller's end-customer identifiers. Nothing on
    the timeline is worth shipping a payload for, so none is shipped.
    """
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-payload"
    )
    digest = (
        await db_session.execute(
            select(OrderEvent.payload).where(
                OrderEvent.order_id == order_id, OrderEvent.kind == "order.paid"
            )
        )
    ).scalar_one()["request_digest"]

    r = await _read(integration_client, key_id, secret, "acme-payload")

    assert digest not in r.text


# ---------- failure reason ----------


async def test_a_supplier_failure_surfaces_a_coded_failure_reason(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The reseller's only signal that a ``fulfilling`` order has stopped moving.

    The order row stays ``fulfilling`` when a task fails — nothing advances it
    — so status alone would say "in progress" forever.
    """
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-failed"
    )
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    ).scalar_one()
    item.fulfillment_state = "failed"
    await db_session.commit()

    r = await _read(integration_client, key_id, secret, "acme-failed")

    assert r.status_code == 200, r.text
    assert r.json()["failure_reason"] == "fulfillment_failed"


async def test_a_soft_failure_the_storefront_hides_is_hidden_here_too(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Our own supplier balance running out is not the reseller's failure.

    ``fulfillment`` already draws this line: a low-balance task fails but the
    item stays ``in_progress`` so the storefront keeps saying "processing"
    while an operator tops up and retries. Reading the item's state rather
    than the task's inherits that rule instead of re-deciding it — telling a
    reseller "failed" here would have them refund their end customer for an
    order we are about to deliver.
    """
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-lowbal"
    )
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    task.status = "failed"
    task.last_error = "supplier_low_balance"
    await db_session.commit()

    r = await _read(integration_client, key_id, secret, "acme-lowbal")

    assert r.status_code == 200, r.text
    assert r.json()["failure_reason"] is None
    assert "supplier_low_balance" not in r.text


async def test_an_order_support_closed_reports_order_failed(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-closed"
    )
    r = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/fail",
        headers=admin_headers,
        json={"reason": "supplier permanently out; internal note nobody outside should read"},
    )
    assert r.status_code == 200, r.text

    read = await _read(integration_client, key_id, secret, "acme-closed")

    assert read.status_code == 200, read.text
    assert read.json()["status"] == "failed"
    assert read.json()["failure_reason"] == "order_failed"
    # The operator's free text is an internal note, never a wire field.
    assert "internal note" not in read.text


# ---------- the refund mark ----------


async def test_refunded_usd_is_read_from_the_ledger_not_hardcoded(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Nothing refunds a merchant order yet (M3 owns that), so this field is
    always ``"0.00"`` today — which is exactly how a hardcoded zero would look.

    So the test posts the refund M3 will post: the README's posting table row
    ``D merchant_deposit / C house_payments_received``, referencing the order.
    If the field is computed, it moves.
    """
    merchant_id, key_id, secret, order_id = await _place(
        integration_client, admin_headers, db_session, merchant_order_id="acme-refund"
    )
    before = await _read(integration_client, key_id, secret, "acme-refund")
    assert before.json()["refunded_usd"] == "0.00"

    from yupay.modules.merchants import deposit as merchant_deposit
    from yupay.modules.wallet import service as wallet_service

    deposit_account = await wallet_service.ensure_account(
        db_session,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=merchant_deposit.DEPOSIT_CURRENCY,
    )
    house = await wallet_service.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_payments_received",
        currency=merchant_deposit.DEPOSIT_CURRENCY,
    )
    await wallet_service.post(
        db_session,
        kind="merchant_order_refund",
        legs=[
            wallet_service.Leg(
                account_id=deposit_account.id,
                direction="D",
                amount=Decimal("1.07"),
                currency=merchant_deposit.DEPOSIT_CURRENCY,
            ),
            wallet_service.Leg(
                account_id=house.id,
                direction="C",
                amount=Decimal("1.07"),
                currency=merchant_deposit.DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=f"merchant-order-refund:{order_id}",
        reference=wallet_service.Reference(type="order", id=order_id),
        actor="test",
    )
    await db_session.commit()

    after = await _read(integration_client, key_id, secret, "acme-refund")

    assert after.json()["refunded_usd"] == "1.07"


async def test_a_refund_on_another_order_does_not_mark_this_one(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The refund sum is scoped to the order's own ledger reference."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)
    for oid in ("one", "two"):
        r = await _post_order(
            integration_client,
            key_id,
            secret,
            {"merchant_order_id": oid, "sku_id": sku_id, "expected_price": "1.07"},
        )
        assert r.status_code == 201, r.text
    other_order_id = (await _read(integration_client, key_id, secret, "two")).json()["order_id"]

    from yupay.modules.merchants import deposit as merchant_deposit
    from yupay.modules.wallet import service as wallet_service

    deposit_account = await wallet_service.ensure_account(
        db_session,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=merchant_deposit.DEPOSIT_CURRENCY,
    )
    house = await wallet_service.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_payments_received",
        currency=merchant_deposit.DEPOSIT_CURRENCY,
    )
    await wallet_service.post(
        db_session,
        kind="merchant_order_refund",
        legs=[
            wallet_service.Leg(
                account_id=deposit_account.id,
                direction="D",
                amount=Decimal("1.07"),
                currency=merchant_deposit.DEPOSIT_CURRENCY,
            ),
            wallet_service.Leg(
                account_id=house.id,
                direction="C",
                amount=Decimal("1.07"),
                currency=merchant_deposit.DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=f"merchant-order-refund:{other_order_id}",
        reference=wallet_service.Reference(type="order", id=other_order_id),
        actor="test",
    )
    await db_session.commit()

    assert (await _read(integration_client, key_id, secret, "one")).json()["refunded_usd"] == "0.00"
    assert (await _read(integration_client, key_id, secret, "two")).json()["refunded_usd"] == "1.07"
