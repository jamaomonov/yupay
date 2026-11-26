"""Service-level fulfilment branches: saga guards, stub suppliers, webhook
reconciliation, wallet-gateway preconditions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle
from yupay.core.errors import ConflictError
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
from yupay.modules.fulfillment.models import FulfillmentAttempt, FulfillmentTask
from yupay.modules.orders.models import OrderItem
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.wallet import WalletGateway
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


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


def _seed_unit(db: AsyncSession, *, slug: str, kind: str = "top_up") -> str:
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
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"fs-order-{tag}-pad"},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _pay(client: AsyncClient, *, token: str, order_id: str, tag: str) -> None:
    r = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"fs-intent-{tag}-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": f"fs_{tag}", "payment_id": r.json()["external_id"], "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text


async def _task_for_order(db: AsyncSession, order_id: str) -> FulfillmentTask:
    return (
        await db.execute(select(FulfillmentTask).where(FulfillmentTask.order_id == order_id))
    ).scalar_one()


# ---------- saga guards ----------


async def test_start_for_order_rejects_unpaid_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    sku_id = _seed_unit(db_session, slug="unpaid")
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=951)
    order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="951")

    with pytest.raises(ConflictError, match="fulfilment-ready"):
        await ff_svc.start_for_order(db_session, order_id=order_id)


async def test_start_for_order_rerun_reuses_existing_tasks(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    sku_id = _seed_unit(db_session, slug="rerun")  # no sourcing rule → manual, stays fulfilling
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=952)
    order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="952")
    await _pay(integration_client, token=token, order_id=order_id, tag="952")

    first = await _task_for_order(db_session, order_id)
    rerun = await ff_svc.start_for_order(db_session, order_id=order_id)
    assert [t.id for t in rerun] == [first.id]


async def test_a_pack_cart_gets_one_task_per_piece(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """«110 × 3 + 341» on one payment: the storefront sends every piece as its
    own ``qty: 1`` line (``@yupay/utils`` pack-cart), and each becomes its own
    task — one supplier call per pack, retried or refunded alone."""
    a = _seed_unit(db_session, slug="cart-a")
    b = _seed_unit(db_session, slug="cart-b")
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=953)

    def line(sku_id: str) -> dict[str, object]:
        return {"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}

    r = await integration_client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "fs-order-953-cart-pad"},
        json={"currency": "USD", "items": [line(a), line(a), line(a), line(b)]},
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert len(order["items"]) == 4
    assert Decimal(order["total_usd"]) == Decimal("6.00")
    await _pay(integration_client, token=token, order_id=order["id"], tag="953")

    tasks = (
        (
            await db_session.execute(
                select(FulfillmentTask).where(FulfillmentTask.order_id == order["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(tasks) == 4
    assert len({t.order_item_id for t in tasks}) == 4


# ---------- stub suppliers: fail at start, cancel hook errors ----------


@pytest.fixture
async def _stub_routed_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> tuple[str, str]:
    """An order whose SKU is force-routed to the unintegrated ``steam`` stub."""
    from yupay.modules.sourcing.models import SkuSourcingRule

    sku_id = _seed_unit(db_session, slug="stub")
    await db_session.commit()
    db_session.add(SkuSourcingRule(sku_id=sku_id, mode="force_supplier", supplier_slug="steam"))
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=953)
    await _grant_admin(db_session, tg_id=953)
    order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="953")
    await _pay(integration_client, token=token, order_id=order_id, tag="953")
    return order_id, token


async def test_stub_supplier_fails_task_at_start(
    db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    assert task.supplier == "steam"
    assert task.status == "failed"
    assert task.last_error is not None


async def test_cancel_records_failing_cancel_hook(
    integration_client: AsyncClient, db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    order_id, token = _stub_routed_order
    task = await _task_for_order(db_session, order_id)

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    cancel_errors = (
        (
            await db_session.execute(
                select(FulfillmentAttempt).where(
                    FulfillmentAttempt.task_id == task.id,
                    FulfillmentAttempt.kind == "cancel",
                    FulfillmentAttempt.status == "error",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(cancel_errors) == 1  # stub's cancel hook raised, recorded, not fatal


async def test_force_complete_rejected_for_cancelled_task(
    integration_client: AsyncClient, db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    order_id, token = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    await ff_svc.cancel_task(db_session, task_id=task.id)
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task.id}/force-complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"artifact_kind": "voucher_code", "artifact": {"code": "X"}},
    )
    assert r.status_code == 409, r.text


# ---------- webhook reconciliation ----------


async def test_process_webhook_update_terminal_short_circuits(
    integration_client: AsyncClient, db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)

    # failed → idempotent no-op
    out = await ff_svc.process_webhook_update(db_session, task_id=task.id)
    assert out.status == "failed"

    await ff_svc.cancel_task(db_session, task_id=task.id)
    await db_session.commit()
    out = await ff_svc.process_webhook_update(db_session, task_id=task.id)
    assert out.status == "cancelled"


async def test_process_webhook_update_check_status_error_is_recorded(
    integration_client: AsyncClient, db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    # Re-arm the task: pretend the stub supplier accepted it earlier.
    await db_session.execute(
        update(FulfillmentTask).where(FulfillmentTask.id == task.id).values(status="in_progress")
    )
    await db_session.commit()

    out = await ff_svc.process_webhook_update(db_session, task_id=task.id)
    assert out.status == "in_progress"  # unchanged — supplier unreachable

    status_errors = (
        (
            await db_session.execute(
                select(FulfillmentAttempt).where(
                    FulfillmentAttempt.task_id == task.id,
                    FulfillmentAttempt.kind == "status_check",
                    FulfillmentAttempt.status == "error",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(status_errors) == 1


async def test_process_webhook_update_in_progress_manual_is_noop(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    sku_id = _seed_unit(db_session, slug="manual-noop")
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=954)
    order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="954")
    await _pay(integration_client, token=token, order_id=order_id, tag="954")

    task = await _task_for_order(db_session, order_id)
    assert task.supplier == "manual"
    out = await ff_svc.process_webhook_update(db_session, task_id=task.id)
    assert out.status == "in_progress"


# ---------- wallet gateway preconditions ----------


async def test_wallet_gateway_rejects_guest_and_zero_amount(db_session: AsyncSession) -> None:
    from yupay.modules.orders.models import Order

    gw = WalletGateway()
    guest_order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status="pending_payment",
        currency="USD",
        total_usd=Decimal("1"),
        total_charged=Decimal("1"),
    )
    with pytest.raises(PaymentGatewayError, match="logged-in user"):
        await gw.create_intent(db=db_session, order=guest_order, return_url="")

    zero_order = Order(
        id=new_id(),
        user_id=new_id(),
        status="pending_payment",
        currency="USD",
        total_usd=Decimal("0"),
        total_charged=Decimal("0"),
    )
    with pytest.raises(PaymentGatewayError, match="non-positive"):
        await gw.create_intent(db=db_session, order=zero_order, return_url="")


async def test_wallet_payment_without_balance_conflicts(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A user with no wallet account at all: the gateway creates the account
    on the fly (zero balance) and refuses with «insufficient»."""
    sku_id = _seed_unit(db_session, slug="broke")
    await db_session.commit()
    token = await _login_user(integration_client, tg_id=955)
    order_id = await _order(integration_client, token=token, sku_id=sku_id, tag="955")

    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "fs-intent-955b-pad"},
        json={"order_id": order_id, "provider": "wallet"},
    )
    assert r.status_code == 409, r.text
    assert "insufficient" in r.json()["detail"]


async def test_an_inventory_routed_task_can_be_cancelled(
    integration_client: AsyncClient, db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    """`inventory` is a route, not a supplier, and the cancel path forgot.

    `_apply_cancel` looked the task's `supplier` up in `REGISTRY`, which holds
    external integrations only. A task our own warehouse served carries
    `supplier = "inventory"`, so the lookup answered `unknown fulfilment
    supplier: inventory` and 404'd — **before** the `try` whose docstring
    promises the supplier call is best-effort and cannot block the local flip.
    The promise was made by a comment and broken by the line above it.

    Found on production on 2026-09-10 by an operator who could not close a
    refunded merchant order. Nothing our own stock served could be closed by
    hand, and that is every voucher SKU we hold.
    """
    order_id, token = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    task.supplier = "inventory"
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    attempts = (
        (
            await db_session.execute(
                select(FulfillmentAttempt).where(
                    FulfillmentAttempt.task_id == task.id,
                    FulfillmentAttempt.kind == "cancel",
                )
            )
        )
        .scalars()
        .all()
    )
    # Recorded as ``ok``: there was no external supplier to refuse, so calling
    # this an error would put a false failure in the operator's inbox.
    assert [a.status for a in attempts] == ["ok"]
    assert attempts[0].payload["note"].startswith("inventory route")


async def test_a_task_whose_supplier_slug_is_unknown_can_still_be_cancelled(
    integration_client: AsyncClient, db_session: AsyncSession, _stub_routed_order: tuple[str, str]
) -> None:
    """A retired integration must not make its old orders uncloseable.

    Same shape as the inventory case and the same fix: the lookup lives inside
    the `try`, so an unknown slug is recorded and the task still flips. There
    is nothing to settle with a supplier once the order is gone, and refusing
    to close the order helps nobody.
    """
    order_id, token = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    task.supplier = "a-supplier-we-retired"
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    errors = (
        (
            await db_session.execute(
                select(FulfillmentAttempt).where(
                    FulfillmentAttempt.task_id == task.id,
                    FulfillmentAttempt.kind == "cancel",
                    FulfillmentAttempt.status == "error",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(errors) == 1


# ---------- transient status-check failures stay quiet (check_noise) ----------


@pytest.fixture
def _alerts(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """The errors ``_record_attempt`` decided to announce."""
    seen: list[str | None] = []

    def _capture(task: FulfillmentTask, *, kind: str, error: str | None) -> None:
        seen.append(error)

    monkeypatch.setattr(ff_svc, "_alert_fulfillment_error", _capture)
    monkeypatch.setattr(ff_svc, "_dispatch_alert", lambda _coro: None)
    return seen


async def test_a_throttled_status_check_is_logged_but_not_announced(
    db_session: AsyncSession,
    _stub_routed_order: tuple[str, str],
    _alerts: list[str | None],
) -> None:
    """2026-11-17: one buyer's 36 fzr lines filled the ops chat with 429s for
    orders that were all delivered. Fresh trouble on a read is noise."""
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)

    await ff_svc._record_attempt(
        db_session,
        task=task,
        kind="status_check",
        status="error",
        error="Слишком много запросов. Повторите через 9 с.",
        transient=True,
    )
    await db_session.flush()

    assert _alerts == []
    assert task.attempts_count >= 1


async def test_a_transient_failure_is_announced_once_nothing_succeeded_for_five_minutes(
    db_session: AsyncSession,
    _stub_routed_order: tuple[str, str],
    _alerts: list[str | None],
) -> None:
    """Measured from the last good check, so an outage whose text keeps
    changing (ConnectTimeout, ConnectError) still announces itself."""
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    long_ago = datetime.now(UTC) - timedelta(minutes=6)
    db_session.add(
        FulfillmentAttempt(
            id=new_id(),
            task_id=task.id,
            kind="status_check",
            status="ok",
            payload={},
            created_at=long_ago,
        )
    )
    await db_session.flush()

    await ff_svc._record_attempt(
        db_session,
        task=task,
        kind="status_check",
        status="error",
        error="ConnectTimeout",
        transient=True,
    )

    assert len(_alerts) == 1


async def test_a_real_status_check_error_is_still_announced_at_once(
    db_session: AsyncSession,
    _stub_routed_order: tuple[str, str],
    _alerts: list[str | None],
) -> None:
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)

    await ff_svc._record_attempt(
        db_session, task=task, kind="status_check", status="error", error="order not found"
    )

    assert len(_alerts) == 1


async def test_a_level_up_pack_refusal_is_not_announced(
    db_session: AsyncSession,
    _stub_routed_order: tuple[str, str],
    _alerts: list[str | None],
) -> None:
    """2026-11-26: Free Fire Level Up Packs are refused whenever the account's
    level is out of range — routine, refunded on their own, and they were most
    of the chat. Owner's call: no alert for them."""
    order_id, _ = _stub_routed_order
    task = await _task_for_order(db_session, order_id)
    item = await db_session.get(OrderItem, task.order_item_id)
    assert item is not None
    sku = await db_session.get(Sku, item.sku_id)
    assert sku is not None
    sku.sku_code = "freefire_cis-level-up-6"
    await db_session.flush()

    await ff_svc._record_attempt(
        db_session,
        task=task,
        kind="status_check",
        status="error",
        error="fzr refunded the order (refund)",
    )

    assert _alerts == []
