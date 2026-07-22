"""Payments: terminal webhook outcomes, refund guards, admin list filters.

Targets the previously-untested error branches in ``payments/service.py``:
failed/cancelled webhooks, unmatched webhooks, simulate-webhook guards,
refund validation / dry-run / gateway-rejection paths, list filters.
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
from yupay.modules.payments.gateways import REGISTRY, StubGateway
from yupay.modules.payments.models import Payment, PaymentAttempt
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


class _AvailableNoRefundGateway(StubGateway):
    """An *available* acquirer whose ``refund`` still isn't implemented — the
    exact shape the refund-rejection path guards against (a live gateway that
    can't settle a refund). ``StubGateway.refund`` already raises
    ``PaymentNotIntegratedError``; we only flip ``available`` to ``True`` so the
    service actually calls it instead of taking the dry-run stub path."""

    @property
    def available(self) -> bool:
        return True


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
        slug="dota",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Dota 2")],
    )
    product = Product(
        id=new_id(),
        slug="dota-points",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Dota Points")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="dota-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _order_with_intent(
    client: AsyncClient, *, token: str, sku_id: str, tag: str
) -> tuple[str, str, str]:
    """Returns (order_id, payment_id, external_id) with a pending mock intent."""
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"ep-order-{tag}-pad"},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]
    r = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"ep-intent-{tag}-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    return order_id, r.json()["id"], r.json()["external_id"]


async def _webhook(client: AsyncClient, *, external_id: str, event: str, outcome: str):
    return await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps({"event_id": event, "payment_id": external_id, "outcome": outcome}),
        headers={"content-type": "application/json"},
    )


# ---------- terminal webhook outcomes ----------


async def test_failed_webhook_marks_payment_failed(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=801)
    _, payment_id, external_id = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="801"
    )
    wh = await _webhook(
        integration_client, external_id=external_id, event="ep_f_801", outcome="failed"
    )
    assert wh.status_code == 200, wh.text

    r = await integration_client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {await _login_user(integration_client, tg_id=801)}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"
    assert r.json()["failed_at"] is not None


async def test_cancelled_webhook_marks_payment_cancelled(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=802)
    _, payment_id, external_id = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="802"
    )
    wh = await _webhook(
        integration_client, external_id=external_id, event="ep_c_802", outcome="cancelled"
    )
    assert wh.status_code == 200, wh.text

    r = await integration_client.get(
        f"/api/v1/payments/{payment_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.json()["status"] == "cancelled"
    assert r.json()["failed_at"] is None


async def test_webhook_for_unknown_payment_is_404(integration_client: AsyncClient) -> None:
    wh = await _webhook(
        integration_client, external_id="mock_does-not-exist", event="ep_x_001", outcome="succeeded"
    )
    assert wh.status_code == 404, wh.text


async def test_rejected_webhook_audit_row_survives_the_4xx(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The signature/shape rejection is committed before the 4xx is raised —
    otherwise the request rollback would erase the audit trail the code
    explicitly promises to keep."""
    from yupay.modules.payments.models import PaymentWebhook

    r = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps({"bad": "shape"}),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, r.text

    rejected = (
        (
            await db_session.execute(
                select(PaymentWebhook).where(PaymentWebhook.signature_ok.is_(False))
            )
        )
        .scalars()
        .all()
    )
    assert len(rejected) == 1


# ---------- simulate-webhook guards ----------


async def test_simulate_webhook_guards(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=803)
    await _grant_admin(db_session, tg_id=803)
    headers = {"Authorization": f"Bearer {token}"}

    r = await integration_client.post(
        f"/api/v1/admin/payments/{new_id()}/simulate-webhook",
        headers=headers,
        json={"outcome": "succeeded"},
    )
    assert r.status_code == 404, r.text

    order_id, payment_id, external_id = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="803"
    )
    await _webhook(
        integration_client, external_id=external_id, event="ep_s_803", outcome="succeeded"
    )
    r = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/simulate-webhook",
        headers=headers,
        json={"outcome": "succeeded"},
    )
    assert r.status_code == 409, r.text  # not pending any more

    stub = Payment(
        id=new_id(),
        order_id=order_id,
        provider="click",
        status="pending",
        amount=Decimal("1.50"),
        currency="USD",
        external_id=f"click_{new_id()}",
        extra_metadata={},
    )
    db_session.add(stub)
    await db_session.commit()
    r = await integration_client.post(
        f"/api/v1/admin/payments/{stub.id}/simulate-webhook",
        headers=headers,
        json={"outcome": "succeeded"},
    )
    assert r.status_code == 409, r.text  # mock-only


# ---------- refund guards ----------


async def test_refund_validation_errors(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=804)
    await _grant_admin(db_session, tg_id=804)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "ep-refund-804-padpad"}

    r = await integration_client.post(
        f"/api/v1/admin/payments/{new_id()}/refund", headers=headers, json={}
    )
    assert r.status_code == 404, r.text

    _, payment_id, external_id = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="804"
    )
    await _webhook(
        integration_client, external_id=external_id, event="ep_r_804", outcome="succeeded"
    )

    r = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={**headers, "Idempotency-Key": "ep-refund-804b-padpad"},
        json={"amount": "-1"},
    )
    assert r.status_code == 422, r.text

    r = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/refund",
        headers={**headers, "Idempotency-Key": "ep-refund-804c-padpad"},
        json={"amount": "99999"},
    )
    assert r.status_code == 422, r.text


async def test_refund_dry_run_for_stub_provider(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """A succeeded payment on a not-yet-integrated provider (click) refunds in
    dry-run mode: state flips, ledger books, no network call is attempted."""
    token = await _login_user(integration_client, tg_id=805)
    await _grant_admin(db_session, tg_id=805)
    order_id, _, _ = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="805"
    )
    stub = Payment(
        id=new_id(),
        order_id=order_id,
        provider="click",
        status="succeeded",
        amount=Decimal("1.50"),
        currency="USD",
        external_id=f"click_{new_id()}",
        extra_metadata={},
    )
    db_session.add(stub)
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/payments/{stub.id}/refund",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "ep-refund-805-padpad"},
        json={"reason": "test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refunded"
    assert body["extra_metadata"]["last_refund"]["dry_run"] is True


async def test_refund_rejected_by_gateway(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An available acquirer with no refund API — the gateway raises and the
    service answers 409 with an error attempt recorded, leaving the payment
    refundable."""
    monkeypatch.setitem(
        REGISTRY,
        "norefund",
        _AvailableNoRefundGateway(provider="norefund", todo_message="no refund API"),
    )
    token = await _login_user(integration_client, tg_id=806)
    await _grant_admin(db_session, tg_id=806)
    order_id, _, _ = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="806"
    )
    payment = Payment(
        id=new_id(),
        order_id=order_id,
        provider="norefund",
        status="succeeded",
        amount=Decimal("1.50"),
        currency="USD",
        external_id=f"norefund_{new_id()}",
        extra_metadata={},
    )
    db_session.add(payment)
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/payments/{payment.id}/refund",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "ep-refund-806-padpad"},
        json={},
    )
    assert r.status_code == 409, r.text

    attempts = (
        (
            await db_session.execute(
                select(PaymentAttempt).where(
                    PaymentAttempt.payment_id == payment.id,
                    PaymentAttempt.kind == "refund",
                    PaymentAttempt.status == "error",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1


# ---------- admin list filters ----------


async def test_admin_list_filters(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=807)
    await _grant_admin(db_session, tg_id=807)
    headers = {"Authorization": f"Bearer {token}"}
    order_id, payment_id, external_id = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="807"
    )
    await _webhook(
        integration_client, external_id=external_id, event="ep_l_807", outcome="succeeded"
    )

    r = await integration_client.get(
        f"/api/v1/admin/payments?order_id={order_id}&provider=mock&status_filter=succeeded",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()["items"]] == [payment_id]

    r = await integration_client.get(
        "/api/v1/admin/payments?provider=nope&status_filter=failed", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = await integration_client.get(
        "/api/v1/admin/webhooks?provider=mock&signature_ok=true", headers=headers
    )
    assert r.status_code == 200, r.text
    assert any(w["external_event_id"] == "ep_l_807" for w in r.json()["items"])

    r = await integration_client.get(
        "/api/v1/admin/webhooks?provider=mock&signature_ok=false", headers=headers
    )
    assert r.status_code == 200
    assert all(w["signature_ok"] is False for w in r.json()["items"])


# ---------- intent guards ----------


async def test_active_payment_with_other_provider_conflicts(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=808)
    order_id, _, _ = await _order_with_intent(
        integration_client, token=token, sku_id=_seed_sku, tag="808"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "ep-intent-808b-pad"},
        json={"order_id": order_id, "provider": "wallet"},
    )
    assert r.status_code == 409, r.text


async def test_create_intent_unknown_order_service_level(db_session: AsyncSession) -> None:
    import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle

    from yupay.core.errors import NotFoundError
    from yupay.modules.payments import service as payments_svc

    with pytest.raises(NotFoundError):
        await payments_svc.create_intent(
            db_session, order_id=new_id(), provider="mock", return_url=None
        )
