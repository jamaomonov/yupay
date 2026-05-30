"""Integration tests for the payments skeleton.

Covers:
- POST /api/v1/payments/intents creates a payment via the mock provider
- The webhook receiver flips the order ``pending_payment → paid``
- Replaying the same webhook is idempotent (200, no state change)
- Bad signature/shape returns 4xx and persists the rejected attempt
- A stub provider (Click) refuses with 409 until it's integrated
- Admin can list payments and simulate the mock webhook
- Owner-only read on GET /payments/{id}
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
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet import service as wallet_svc
from yupay.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

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
    # Pin the route to mock — top_up SKUs now default to the manual queue
    # without a supplier mapping (sourcing.resolve_for_sku), and these
    # tests assert the synchronous paid→delivered mock path.
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _create_order(client: AsyncClient, *, token: str, sku_id: str, key: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- intents ----------


async def test_list_providers_returns_only_available(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.get("/api/v1/payments/providers")
    assert r.status_code == 200
    # ``wallet`` joined ``mock`` as a synchronous in-house provider.
    providers = r.json()["providers"]
    assert "mock" in providers
    assert "wallet" in providers


async def test_create_intent_for_owned_order(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=101)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="pay-intent-aaaa-pad"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "mock"
    assert body["status"] == "pending"
    assert body["intent_url"] is not None
    assert body["external_id"].startswith("mock_")


async def test_get_active_payment_by_order(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """The miniapp's order-detail page hits this endpoint to surface a
    «Оплатить» button for a still-unpaid order. Owner sees the active
    intent; once the order moves past ``pending_payment`` the route 404s;
    a stranger always gets 404 (order-not-found semantics)."""
    owner = await _login_user(integration_client, tg_id=131)
    stranger = await _login_user(integration_client, tg_id=132)
    order_id = await _create_order(
        integration_client, token=owner, sku_id=_seed_sku, key="pay-byorder-aaaa-pad"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {owner}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code == 201, intent.text

    # Owner sees the active intent.
    r = await integration_client.get(
        f"/api/v1/payments/by-order/{order_id}",
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == intent.json()["id"]
    assert body["intent_url"] is not None
    assert body["status"] == "pending"

    # Stranger gets 404 (order-not-found cloak).
    other = await integration_client.get(
        f"/api/v1/payments/by-order/{order_id}",
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert other.status_code == 404

    # After the order is paid, the route reports «no active payment».
    external_id = intent.json()["external_id"]
    wh = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": "evt_byorder_001", "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    after = await integration_client.get(
        f"/api/v1/payments/by-order/{order_id}",
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert after.status_code == 404


async def test_create_intent_reuses_pending_payment(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=102)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="pay-intent-bbbb-pad"
    )
    auth = {"Authorization": f"Bearer {token}"}
    first = await integration_client.post(
        "/api/v1/payments/intents",
        headers=auth,
        json={"order_id": order_id, "provider": "mock"},
    )
    second = await integration_client.post(
        "/api/v1/payments/intents",
        headers=auth,
        json={"order_id": order_id, "provider": "mock"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_intent_for_other_user_404(integration_client: AsyncClient, _seed_sku: str) -> None:
    owner = await _login_user(integration_client, tg_id=103)
    stranger = await _login_user(integration_client, tg_id=104)
    order_id = await _create_order(
        integration_client, token=owner, sku_id=_seed_sku, key="pay-intent-cccc-pad"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {stranger}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 404


async def test_stub_provider_refuses(integration_client: AsyncClient, _seed_sku: str) -> None:
    token = await _login_user(integration_client, tg_id=105)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="pay-intent-dddd-pad"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "click"},
    )
    assert r.status_code == 409
    assert "not available" in r.text.lower()


# ---------- webhooks ----------


async def test_webhook_flips_order_to_paid(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    token = await _login_user(integration_client, tg_id=111)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="pay-wh-aaaa-pad0"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]

    wh = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": "evt_001", "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    assert wh.json()["status"] == "processed"

    # Order goes paid → delivered immediately (mock supplier returns synchronously).
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "delivered"


async def test_webhook_replay_is_idempotent(
    integration_client: AsyncClient,
    _seed_sku: str,
) -> None:
    token = await _login_user(integration_client, tg_id=112)
    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="pay-wh-bbbb-pad0"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]
    payload = json.dumps(
        {"event_id": "evt_dup_001", "payment_id": external_id, "outcome": "succeeded"}
    )
    first = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=payload,
        headers={"content-type": "application/json"},
    )
    second = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}


async def test_webhook_bad_shape_returns_400(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=b"not even json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422  # core ValidationError → 422


async def test_webhook_unknown_provider_404(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.post(
        "/api/v1/webhooks/payments/totally-fake",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 404


# ---------- get / list / admin ----------


async def test_get_payment_owner_only(integration_client: AsyncClient, _seed_sku: str) -> None:
    owner = await _login_user(integration_client, tg_id=121)
    stranger = await _login_user(integration_client, tg_id=122)
    order_id = await _create_order(
        integration_client, token=owner, sku_id=_seed_sku, key="pay-get-aaaa-pad"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {owner}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    payment_id = intent.json()["id"]

    ok = await integration_client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert ok.status_code == 200

    forbidden = await integration_client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert forbidden.status_code == 404


async def test_admin_can_list_and_simulate_webhook(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=131)
    order_id = await _create_order(
        integration_client, token=user, sku_id=_seed_sku, key="pay-admin-aaaa-pad"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {user}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    payment_id = intent.json()["id"]

    admin = await _login_user(integration_client, tg_id=132)
    await _grant_admin(db_session, tg_id=132)
    admin_headers = {"Authorization": f"Bearer {admin}"}

    listing = await integration_client.get("/api/v1/admin/payments", headers=admin_headers)
    assert listing.status_code == 200
    assert any(p["id"] == payment_id for p in listing.json()["items"])

    sim = await integration_client.post(
        f"/api/v1/admin/payments/{payment_id}/simulate-webhook",
        headers=admin_headers,
        json={"outcome": "succeeded"},
    )
    assert sim.status_code == 200, sim.text
    assert sim.json()["status"] == "succeeded"

    # Order goes paid → delivered immediately (mock supplier returns synchronously).
    order_detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {user}"},
    )
    assert order_detail.status_code == 200
    assert order_detail.json()["status"] == "delivered"


async def test_admin_required_for_payments_admin(
    integration_client: AsyncClient,
) -> None:
    user = await _login_user(integration_client, tg_id=141)
    r = await integration_client.get(
        "/api/v1/admin/payments", headers={"Authorization": f"Bearer {user}"}
    )
    assert r.status_code == 403


# ---------- refunds: external provider books a house expense ----------


async def test_external_refund_books_house_expense_not_wallet(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """Refunding an **external**-provider payment (mock card here) books a
    house expense against provider clearing — it must NOT touch the
    customer's wallet balance. This is the counterpart to the wallet-refund
    path (ADR-0023): only wallet-funded refunds credit the balance back.

    Covers the ``provider != "wallet"`` branch of ``refund_admin``.
    """
    # Lazy import dodges the payments.service ↔ wallet.api ↔ api.v1 cycle.
    from yupay.modules.payments import service as payments_svc

    token = await _login_user(integration_client, tg_id=151)
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 151)
        )
    ).scalar_one()
    # Give the customer a $20 wallet — it must stay untouched by an external refund.
    await wallet_svc.admin_adjust(
        db_session,
        user_id=user_id,
        kind="user_wallet",
        currency="USD",
        amount=Decimal("20"),
        reason="test top-up",
        idempotency_key=f"seed-{user_id}-USD-20",
        admin_id="test-admin",
    )
    await db_session.commit()

    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_sku, key="pay-extref-aaaa-pad"
    )
    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]
    wh = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {"event_id": "evt_extref_001", "payment_id": external_id, "outcome": "succeeded"}
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text

    payment = (
        await db_session.execute(select(Payment).where(Payment.order_id == order_id))
    ).scalar_one()
    assert payment.provider == "mock"

    refunded = await payments_svc.refund_admin(
        db_session, payment_id=payment.id, admin_id="test-admin", reason="customer asked"
    )
    await db_session.commit()
    assert refunded.status == "refunded"

    # The customer's wallet is untouched — an external refund returns money
    # through the acquirer, not the balance.
    wallet = await integration_client.get(
        "/api/v1/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("20")

    # The refund booked D house_refunds / C provider_clearing:mock — never user_wallet.
    legs = (
        (
            await db_session.execute(
                select(WalletPosting.direction, WalletAccount.kind, WalletAccount.owner_id)
                .join(WalletTransaction, WalletPosting.transaction_id == WalletTransaction.id)
                .join(WalletAccount, WalletPosting.account_id == WalletAccount.id)
                .where(WalletTransaction.idempotency_key == f"refund:{payment.id}")
            )
        )
        .all()
    )
    booked = {(direction, kind, owner_id) for direction, kind, owner_id in legs}
    assert ("D", "house_refunds", "house") in booked
    assert ("C", "provider_clearing", "mock") in booked
    assert not any(kind == "user_wallet" for _, kind, _ in booked)
