"""Integration tests for the fulfilment skeleton.

End-to-end flow:
- create order → pay via mock provider → webhook flips order to ``paid``
  → fulfillment auto-starts → mock supplier returns artifact → order
  reaches ``delivered`` and a ``deliveries`` row exists.

Also covers:
- owner-only access to ``/orders/{id}/deliveries``
- admin can list, retry, and cancel tasks
- retry of a succeeded task is rejected
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
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
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="cs2",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="CS2")],
    )
    product = Product(
        id=new_id(),
        slug="cs2-coins",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Coins")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="cs2-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("0.99"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    # Explicit route → mock. Since top_up SKUs now default to the manual
    # queue when they lack a supplier mapping (see sourcing.resolve_for_sku),
    # these tests pin the route so they exercise the mock-fulfilment path
    # they were written for.
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _pay_and_fulfill(client: AsyncClient, *, token: str, sku_id: str, key_suffix: str) -> str:
    """Helper: create order, create intent, post webhook → returns order_id (paid+delivered)."""
    create = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"fulfill-{key_suffix}"},
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]
    intent = await client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-fulfillment-routes-01-padpadpad",
        },
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt_{key_suffix}",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


# ---------- happy path ----------


async def test_paid_order_walks_to_delivered(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=201)
    order_id = await _pay_and_fulfill(
        integration_client, token=token, sku_id=_seed_sku, key_suffix="happy-aaaa"
    )

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "delivered"
    assert body["paid_at"] is not None
    assert body["delivered_at"] is not None

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deliveries.status_code == 200, deliveries.text
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["channel"] == "in_app"
    # Seed product is ``kind="top_up"`` so MockFulfiller emits a receipt
    # artifact (not a voucher code — that branch is exercised when the
    # product is ``kind="voucher"``). See modules/fulfillment/suppliers/mock.py.
    assert items[0]["artifact_kind"] == "topup_receipt"
    # ``external_id`` is stored on the row for admin audit, but the
    # customer-facing route strips it (see _CUSTOMER_HIDDEN_ARTIFACT_KEYS
    # in routes.py). ``sku_id`` stays so the UI can still cross-reference.
    assert "external_id" not in items[0]["artifact"]
    assert items[0]["artifact"]["sku_id"] == _seed_sku


async def test_deliveries_owner_only(integration_client: AsyncClient, _seed_sku: str) -> None:
    owner = await _login_user(integration_client, tg_id=211)
    stranger = await _login_user(integration_client, tg_id=212)
    order_id = await _pay_and_fulfill(
        integration_client, token=owner, sku_id=_seed_sku, key_suffix="owner-bbbb"
    )
    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert r.status_code == 404


# ---------- admin ----------


async def test_admin_can_list_tasks(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=221)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="admin-cccc"
    )
    admin = await _login_user(integration_client, tg_id=222)
    await _grant_admin(db_session, tg_id=222)

    r = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers={"Authorization": f"Bearer {admin}"},
        params={"order_id": order_id},
    )
    assert r.status_code == 200, r.text
    tasks = r.json()["items"]
    assert len(tasks) == 1
    assert tasks[0]["status"] == "succeeded"
    assert tasks[0]["supplier"] == "mock"
    assert tasks[0]["attempts_count"] >= 1


async def test_admin_retry_rejects_succeeded_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=231)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="retry-dddd"
    )
    admin = await _login_user(integration_client, tg_id=232)
    await _grant_admin(db_session, tg_id=232)
    admin_headers = {"Authorization": f"Bearer {admin}"}

    listing = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers=admin_headers,
        params={"order_id": order_id},
    )
    task_id = listing.json()["items"][0]["id"]

    retry = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/retry",
        headers=admin_headers,
    )
    assert retry.status_code == 409


async def test_admin_cancel_rejects_succeeded_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=241)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="cancel-eeee"
    )
    admin = await _login_user(integration_client, tg_id=242)
    await _grant_admin(db_session, tg_id=242)
    admin_headers = {"Authorization": f"Bearer {admin}"}

    task_id = (
        await integration_client.get(
            "/api/v1/admin/fulfillment/tasks",
            headers=admin_headers,
            params={"order_id": order_id},
        )
    ).json()["items"][0]["id"]

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/cancel",
        headers=admin_headers,
    )
    assert r.status_code == 409


async def test_admin_required_for_fulfillment_admin(
    integration_client: AsyncClient,
) -> None:
    user = await _login_user(integration_client, tg_id=251)
    r = await integration_client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert r.status_code == 403


# ---------- manual fulfilment ----------


@pytest.fixture
async def _seed_sku_manual(db_session: AsyncSession, _seed_sku: str) -> str:
    """Override the seed SKU's sourcing rule to ``mode='manual'`` so paid
    orders for it route to ``ManualFulfiller`` and park in ``in_progress``
    instead of auto-delivering.

    ``_seed_sku`` already pins ``force_supplier=mock``; we upsert via
    ``set_rule`` (not a raw INSERT) so the row is replaced, not
    duplicated."""
    from yupay.modules.sourcing import service as sourcing_svc

    await sourcing_svc.set_rule(
        db_session,
        sku_id=_seed_sku,
        mode="manual",
        supplier_slug=None,
        admin_id="test",
    )
    await db_session.commit()
    return _seed_sku


async def _pay_to_in_progress(
    client: AsyncClient, *, token: str, sku_id: str, key_suffix: str
) -> str:
    """Same as ``_pay_and_fulfill`` but used with a ``manual`` SKU — after the
    webhook the order is ``fulfilling``, not ``delivered``."""
    create = await client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"manual-{key_suffix}",
        },
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]
    intent = await client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-fulfillment-routes-02-padpadpad",
        },
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt-manual-{key_suffix}",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


async def _task_for_order(
    client: AsyncClient, admin_token: str, order_id: str
) -> dict[str, object]:
    listing = await client.get(
        "/api/v1/admin/fulfillment/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"order_id": order_id},
    )
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert items, "expected at least one task"
    return items[0]


async def test_manual_task_lands_in_progress(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku_manual: str,
) -> None:
    user = await _login_user(integration_client, tg_id=261)
    order_id = await _pay_to_in_progress(
        integration_client, token=user, sku_id=_seed_sku_manual, key_suffix="lands-fff"
    )
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert detail.json()["status"] == "fulfilling"
    assert detail.json()["delivered_at"] is None

    admin = await _login_user(integration_client, tg_id=262)
    await _grant_admin(db_session, tg_id=262)
    task = await _task_for_order(integration_client, admin, order_id)
    assert task["supplier"] == "manual"
    assert task["status"] == "in_progress"

    # No delivery yet.
    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert deliveries.json()["items"] == []


async def test_admin_completes_manual_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku_manual: str,
) -> None:
    user = await _login_user(integration_client, tg_id=271)
    order_id = await _pay_to_in_progress(
        integration_client, token=user, sku_id=_seed_sku_manual, key_suffix="ok-gggggg"
    )
    admin = await _login_user(integration_client, tg_id=272)
    await _grant_admin(db_session, tg_id=272)
    headers = {"Authorization": f"Bearer {admin}"}

    task = await _task_for_order(integration_client, admin, order_id)
    complete = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task['id']}/complete",
        headers=headers,
        json={
            "artifact_kind": "voucher_code",
            "artifact": {"code": "MANUAL-TEST-001"},
            "admin_note": "выдано вручную",
        },
    )
    assert complete.status_code == 200, complete.text
    body = complete.json()
    assert body["status"] == "succeeded"
    assert body["admin_note"] == "выдано вручную"
    assert body["completed_by"]

    # Order walks to delivered through _try_settle_order.
    order = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert order.json()["status"] == "delivered"

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {user}"},
    )
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["artifact_kind"] == "voucher_code"
    assert items[0]["artifact"]["code"] == "MANUAL-TEST-001"


async def test_complete_twice_is_409(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku_manual: str,
) -> None:
    user = await _login_user(integration_client, tg_id=281)
    order_id = await _pay_to_in_progress(
        integration_client, token=user, sku_id=_seed_sku_manual, key_suffix="twice-hhh"
    )
    admin = await _login_user(integration_client, tg_id=282)
    await _grant_admin(db_session, tg_id=282)
    headers = {"Authorization": f"Bearer {admin}"}
    task = await _task_for_order(integration_client, admin, order_id)
    body = {"artifact_kind": "voucher_code", "artifact": {"code": "X-1"}}

    first = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task['id']}/complete",
        headers=headers,
        json=body,
    )
    assert first.status_code == 200, first.text

    second = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task['id']}/complete",
        headers=headers,
        json=body,
    )
    assert second.status_code == 409


async def test_complete_on_non_manual_task_is_409(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """A mock-supplier task must not be ‟completable" through the manual
    endpoint — that would bypass the supplier's own bookkeeping."""
    from yupay.modules.fulfillment.models import FulfillmentTask

    user = await _login_user(integration_client, tg_id=291)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="nonman-iii"
    )
    admin = await _login_user(integration_client, tg_id=292)
    await _grant_admin(db_session, tg_id=292)
    headers = {"Authorization": f"Bearer {admin}"}
    task = await _task_for_order(integration_client, admin, order_id)
    # Roll the mock task back to in_progress so the status guard isn't the
    # one rejecting us — we want to assert the supplier guard.
    await db_session.execute(
        update(FulfillmentTask)
        .where(FulfillmentTask.id == task["id"])
        .values(status="in_progress", succeeded_at=None)
    )
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task['id']}/complete",
        headers=headers,
        json={"artifact_kind": "voucher_code", "artifact": {"code": "no"}},
    )
    assert r.status_code == 409, r.text
    assert "not a manual task" in r.text.lower()


async def test_fail_manual_task_sets_reason(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku_manual: str,
) -> None:
    user = await _login_user(integration_client, tg_id=301)
    order_id = await _pay_to_in_progress(
        integration_client, token=user, sku_id=_seed_sku_manual, key_suffix="fail-jjjj"
    )
    admin = await _login_user(integration_client, tg_id=302)
    await _grant_admin(db_session, tg_id=302)
    headers = {"Authorization": f"Bearer {admin}"}
    task = await _task_for_order(integration_client, admin, order_id)

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task['id']}/fail",
        headers=headers,
        json={"reason": "out of stock", "admin_note": "поставщик не отвечает"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["last_error"] == "out of stock"
    assert body["admin_note"] == "поставщик не отвечает"

    # Order stays in fulfilling — admin issues refund separately.
    order = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert order.json()["status"] == "fulfilling"


async def test_complete_requires_admin(
    integration_client: AsyncClient,
    _seed_sku_manual: str,
) -> None:
    user = await _login_user(integration_client, tg_id=311)
    order_id = await _pay_to_in_progress(
        integration_client, token=user, sku_id=_seed_sku_manual, key_suffix="rbac-kkkkk"
    )
    # Non-admin user can't even list tasks, so we cheat and use the same
    # /complete URL with their own token — should 403.
    # Use a placeholder task id; the role guard runs before the lookup.
    r = await integration_client.post(
        "/api/v1/admin/fulfillment/tasks/00000000-0000-0000-0000-000000000000/complete",
        headers={"Authorization": f"Bearer {user}"},
        json={"artifact_kind": "voucher_code", "artifact": {"code": "x"}},
    )
    assert r.status_code == 403
    assert order_id  # used for fixture side-effect; lint-friendly


# ---------- cascade: order termination cancels open tasks ----------


async def test_refund_cancels_open_fulfilment_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku_manual: str,
) -> None:
    """A full refund of a still-fulfilling order cancels its open task.

    The manual SKU parks the task in ``in_progress`` (order ``fulfilling``).
    Refunding the payment must cascade through
    ``fulfillment.service.cancel_open_tasks_for_order``: the task flips to
    ``cancelled`` and the order walks to ``refunded`` — the saga stops trying
    to deliver goods the customer no longer owns.
    """
    # Lazy import dodges the payments.service ↔ fulfillment.service cycle.
    from yupay.modules.payments import service as payments_svc
    from yupay.modules.payments.models import Payment

    user = await _login_user(integration_client, tg_id=321)
    order_id = await _pay_to_in_progress(
        integration_client, token=user, sku_id=_seed_sku_manual, key_suffix="refcanc-lll"
    )
    admin = await _login_user(integration_client, tg_id=322)
    admin_id = await _grant_admin(db_session, tg_id=322)

    before = await _task_for_order(integration_client, admin, order_id)
    assert before["status"] == "in_progress"
    assert before["supplier"] == "manual"

    payment_id = (
        await db_session.execute(select(Payment.id).where(Payment.order_id == order_id))
    ).scalar_one()
    refunded = await payments_svc.refund_admin(
        db_session, payment_id=payment_id, admin_id=admin_id, reason="customer asked"
    )
    await db_session.commit()
    assert refunded.status == "refunded"

    after = await _task_for_order(integration_client, admin, order_id)
    assert after["status"] == "cancelled"

    order = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert order.json()["status"] == "refunded"


async def test_refund_leaves_delivered_task_untouched(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """A refund must NOT retract a task that already ``succeeded``.

    The mock SKU auto-delivers, so the task is ``succeeded`` before the
    refund. The cascade skips terminal tasks: the customer already received
    the code, and clawing back money does not un-deliver it. The task stays
    ``succeeded`` while the order still walks to ``refunded``.
    """
    from yupay.modules.payments import service as payments_svc
    from yupay.modules.payments.models import Payment

    user = await _login_user(integration_client, tg_id=331)
    order_id = await _pay_and_fulfill(
        integration_client, token=user, sku_id=_seed_sku, key_suffix="refkeep-mmm"
    )
    admin = await _login_user(integration_client, tg_id=332)
    admin_id = await _grant_admin(db_session, tg_id=332)

    before = await _task_for_order(integration_client, admin, order_id)
    assert before["status"] == "succeeded"

    payment_id = (
        await db_session.execute(select(Payment.id).where(Payment.order_id == order_id))
    ).scalar_one()
    await payments_svc.refund_admin(db_session, payment_id=payment_id, admin_id=admin_id)
    await db_session.commit()

    after = await _task_for_order(integration_client, admin, order_id)
    assert after["status"] == "succeeded"
