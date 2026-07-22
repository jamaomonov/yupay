"""Provider-lifecycle hooks: settle / reverse / cancel.

These three public helpers are the seam Payme's ``PerformTransaction`` /
``CancelTransaction`` (Task 5) call into so a provider callback reuses the SINGLE
paid/refund chokepoints instead of a second code path that flips order status or
posts the ledger.

- ``settle_provider_payment`` — provider-driven success → payment succeeded, order
  paid, fulfilment started; idempotent.
- ``reverse_provider_payment`` — provider-driven refund of a succeeded payment →
  refunded + the SAME ledger reversal admin refunds book; idempotent.
- ``cancel_pending_provider_payment`` — provider-driven cancel of a pending payment →
  cancelled, no ledger, no fulfilment; idempotent.
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
from sqlalchemy import func, select
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
from yupay.modules.wallet.models import WalletPosting

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> tuple[str, str]:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games-ph",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="dota-ph",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Dota 2")],
    )
    product = Product(
        id=new_id(),
        slug="dota-points-ph",
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
        sku_code="dota-ph-100",
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


@pytest.fixture
async def _seed_voucher_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="vouchers-ph",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ваучеры")],
    )
    brand = Brand(
        id=new_id(),
        slug="netflix-ph",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Netflix")],
    )
    product = Product(
        id=new_id(),
        slug="netflix-gift-ph",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Gift card")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="netflix-ph-10",
        denomination="10",
        region="US",
        price_usd=Decimal("5.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    from yupay.modules.inventory import service as inv_svc

    await inv_svc.bulk_upload(
        db_session, sku_id=sku.id, codes=["PH-A", "PH-B"], uploaded_by="test"
    )
    await db_session.commit()
    return sku.id


async def _create_order(client: AsyncClient, *, token: str, sku_id: str, tag: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"ph-order-{tag}-pad"},
        json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _mock_intent(client: AsyncClient, *, token: str, order_id: str, tag: str) -> str:
    """Create a pending mock intent; returns the payment id."""
    r = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"ph-intent-{tag}-pad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] in ("pending", "requires_action"), r.text
    return r.json()["id"]


async def _load_payment(db: AsyncSession, payment_id: str) -> Payment:
    return (
        await db.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()


# ---------- settle_provider_payment ----------


async def test_settle_provider_payment_pays_and_fulfils(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """A provider ``PerformTransaction`` on a pending intent walks the payment to
    succeeded and the order to paid → delivered (fulfilment started via the single
    ``_mark_payment_succeeded`` chokepoint)."""
    from yupay.modules.payments import service as payments_svc

    token, _ = await _login_user(integration_client, tg_id=921)
    order_id = await _create_order(integration_client, token=token, sku_id=_seed_sku, tag="921")
    payment_id = await _mock_intent(integration_client, token=token, order_id=order_id, tag="921")

    payment = await _load_payment(db_session, payment_id)
    await payments_svc.settle_provider_payment(
        db_session, payment=payment, external_event_id="perform:921"
    )
    await db_session.commit()

    assert payment.status == "succeeded"
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.json()["status"] == "delivered"

    # Idempotent: a second PerformTransaction (retried callback) is a no-op.
    await payments_svc.settle_provider_payment(
        db_session, payment=payment, external_event_id="perform:921"
    )
    await db_session.commit()
    assert payment.status == "succeeded"


# ---------- reverse_provider_payment ----------


async def test_reverse_provider_payment_refunds_and_reverses_ledger(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_voucher_sku: str
) -> None:
    """A provider ``CancelTransaction`` on a performed (succeeded) payment runs the
    SAME ledger reversal admin refunds book — the wallet-funded payment lands the
    money straight back on the customer's balance and the order walks to refunded."""
    from yupay.modules.payments import service as payments_svc
    from yupay.modules.wallet import service as wallet_svc

    token, user_id = await _login_user(integration_client, tg_id=922)
    await wallet_svc.admin_adjust(
        db_session,
        user_id=user_id,
        kind="user_wallet",
        currency="USD",
        amount=Decimal("20"),
        reason="seed",
        idempotency_key=f"seed-{user_id}",
        admin_id="test-admin",
    )
    await db_session.commit()

    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_voucher_sku, tag="922"
    )
    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "ph-wallet-922-pad"},
        json={"order_id": order_id, "provider": "wallet"},
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["status"] == "succeeded"

    payment = (
        await db_session.execute(select(Payment).where(Payment.order_id == order_id))
    ).scalar_one()

    postings_before = (
        await db_session.execute(select(func.count()).select_from(WalletPosting))
    ).scalar_one()

    await payments_svc.reverse_provider_payment(
        db_session, payment=payment, external_event_id="cancel-performed:922"
    )
    await db_session.commit()

    assert payment.status == "refunded"

    # Ledger reversal actually posted (the refund double-entry).
    postings_after = (
        await db_session.execute(select(func.count()).select_from(WalletPosting))
    ).scalar_one()
    assert postings_after > postings_before

    # Money is back on the balance ($20 seeded, $5 charged, $5 refunded → $20).
    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("20")

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.json()["status"] == "refunded"

    # Idempotent: a retried CancelTransaction posts NO second reversal.
    await payments_svc.reverse_provider_payment(
        db_session, payment=payment, external_event_id="cancel-performed:922"
    )
    await db_session.commit()
    postings_final = (
        await db_session.execute(select(func.count()).select_from(WalletPosting))
    ).scalar_one()
    assert postings_final == postings_after
    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("20")


# ---------- cancel_pending_provider_payment ----------


async def test_cancel_pending_provider_payment_no_ledger_no_fulfilment(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """A provider ``CancelTransaction`` on an UNPERFORMED (pending) payment marks it
    cancelled without touching the order status, the ledger, or fulfilment."""
    from yupay.modules.payments import service as payments_svc

    token, _ = await _login_user(integration_client, tg_id=923)
    order_id = await _create_order(integration_client, token=token, sku_id=_seed_sku, tag="923")
    payment_id = await _mock_intent(integration_client, token=token, order_id=order_id, tag="923")

    postings_before = (
        await db_session.execute(select(func.count()).select_from(WalletPosting))
    ).scalar_one()

    payment = await _load_payment(db_session, payment_id)
    await payments_svc.cancel_pending_provider_payment(db_session, payment=payment)
    await db_session.commit()

    assert payment.status == "cancelled"

    # Order never left pending_payment (not paid, not fulfilled).
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.json()["status"] == "pending_payment"

    # No ledger posting was booked.
    postings_after = (
        await db_session.execute(select(func.count()).select_from(WalletPosting))
    ).scalar_one()
    assert postings_after == postings_before

    # Idempotent.
    await payments_svc.cancel_pending_provider_payment(db_session, payment=payment)
    await db_session.commit()
    assert payment.status == "cancelled"
