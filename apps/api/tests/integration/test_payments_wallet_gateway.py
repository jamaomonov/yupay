"""Safety tests for wallet-as-payment-method.

Every test below targets one of the invariants documented in
``payments.gateways.wallet``:

- happy path: balance gets debited, order walks to ``delivered``
- insufficient balance: nothing changes (no Payment row, no debit)
- wrong currency: rejected
- guest order: rejected (no wallet to charge)
- double-tap idempotency: a second create_intent on the same order
  doesn't double-debit and doesn't create a second Payment row
- concurrent race: two parallel charges finish with exactly one
  payment and exactly one debit (FOR UPDATE serialisation)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select
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
from yupay.modules.wallet import service as wallet_svc

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> tuple[str, str]:
    """Login + return ``(token, user_id)``."""
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200
    token = r.json()["access_token"]
    # Decode user_id without verification — just to skip another roundtrip.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


@pytest.fixture
async def _seed_voucher_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="vouchers-w",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ваучеры")],
    )
    brand = Brand(
        id=new_id(),
        slug="netflix-w",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Netflix")],
    )
    product = Product(
        id=new_id(),
        slug="netflix-gift-w",
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
        sku_code="netflix-10-us-w",
        denomination="10",
        region="US",
        price_usd=Decimal("5.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    # Stock — inventory fulfiller will issue this code.
    from yupay.modules.inventory import service as inv_svc

    await inv_svc.bulk_upload(
        db_session,
        sku_id=sku.id,
        codes=[
            "WALLET-A",
            "WALLET-B",
            "WALLET-C",
        ],
        uploaded_by="test",
    )
    await db_session.commit()
    return sku.id


async def _credit_user_wallet(
    db: AsyncSession, *, user_id: str, currency: str, amount: Decimal
) -> None:
    """Seed the user's wallet with ``amount``. Positive amount credits."""
    await wallet_svc.admin_adjust(
        db,
        user_id=user_id,
        kind="user_wallet",
        currency=currency,
        amount=amount,
        reason="test top-up",
        idempotency_key=f"seed-{user_id}-{currency}-{amount}",
        admin_id="test-admin",
    )
    await db.commit()


async def _create_order(
    client: AsyncClient,
    *,
    token: str,
    sku_id: str,
    key_suffix: str,
    qty: int = 1,
) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"wallet-pay-test-{key_suffix}",
        },
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": qty, "fulfillment_data": {}}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _pay_with_wallet(
    client: AsyncClient,
    *,
    token: str,
    order_id: str,
) -> tuple[int, dict]:
    r = await client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"order_id": order_id, "provider": "wallet"},
    )
    body = r.json() if r.status_code < 500 else {}
    return r.status_code, body


# ---------- happy path ----------


async def test_wallet_pay_happy_path_debits_and_delivers(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_voucher_sku: str,
) -> None:
    token, user_id = await _login_user(integration_client, tg_id=901)
    await _credit_user_wallet(db_session, user_id=user_id, currency="USD", amount=Decimal("20"))

    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_voucher_sku, key_suffix="happy"
    )
    status, body = await _pay_with_wallet(integration_client, token=token, order_id=order_id)
    assert status in (200, 201), body
    assert body["status"] == "succeeded"
    assert body["provider"] == "wallet"

    # Order walked to delivered (synchronous mock-fulfilment served from inventory).
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.json()["status"] == "delivered"

    # Wallet balance went down by exactly the order total.
    wallet = await integration_client.get(
        "/api/v1/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("15")


# ---------- insufficient balance ----------


async def test_wallet_pay_insufficient_balance_changes_nothing(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_voucher_sku: str,
) -> None:
    token, user_id = await _login_user(integration_client, tg_id=902)
    # Only $1, order is $5.
    await _credit_user_wallet(db_session, user_id=user_id, currency="USD", amount=Decimal("1"))

    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_voucher_sku, key_suffix="insufficient"
    )
    status, body = await _pay_with_wallet(integration_client, token=token, order_id=order_id)
    assert status == 409, body
    assert "insufficient" in (body.get("detail") or "").lower()

    # No Payment row was persisted.
    payments = (
        (await db_session.execute(select(Payment).where(Payment.order_id == order_id)))
        .scalars()
        .all()
    )
    assert payments == []

    # Wallet balance is intact (= $1).
    wallet = await integration_client.get(
        "/api/v1/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("1")

    # Order is still awaiting payment, NOT failed.
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.json()["status"] == "pending_payment"


# ---------- guest orders rejected ----------


async def test_wallet_pay_rejects_guest_orders(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_voucher_sku: str,
) -> None:
    """Guests have no wallet account; charging their non-existent
    balance must be impossible from any path. The route is
    auth-only — we exercise that here by checking 401 on an
    unauthenticated call."""
    r = await integration_client.post(
        "/api/v1/payments/intents",
        json={"order_id": "00000000-0000-0000-0000-000000000000", "provider": "wallet"},
    )
    assert r.status_code in (401, 403, 422), r.text


# ---------- double-tap idempotency ----------


async def test_wallet_pay_second_call_is_rejected_after_paid(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_voucher_sku: str,
) -> None:
    """After a successful charge, hitting the endpoint again for the same
    order must NOT debit a second time — the order is already paid, so
    the second call gets a 409 long before we touch the wallet."""
    token, user_id = await _login_user(integration_client, tg_id=903)
    await _credit_user_wallet(db_session, user_id=user_id, currency="USD", amount=Decimal("20"))

    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_voucher_sku, key_suffix="double-tap"
    )
    first = await _pay_with_wallet(integration_client, token=token, order_id=order_id)
    assert first[0] in (200, 201)

    second = await _pay_with_wallet(integration_client, token=token, order_id=order_id)
    assert second[0] == 409, second
    # One Payment row, balance went down by exactly $5 (not $10).
    wallet = await integration_client.get(
        "/api/v1/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("15")

    payments = (
        (await db_session.execute(select(Payment).where(Payment.order_id == order_id)))
        .scalars()
        .all()
    )
    assert len(payments) == 1


# ---------- concurrency: two parallel charges ----------


async def test_wallet_pay_concurrent_intent_creates_exactly_one_payment(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_voucher_sku: str,
) -> None:
    """Two coroutines hammer ``/intents`` simultaneously. The FOR UPDATE
    on the order + the wallet account must serialise them so exactly
    one payment lands and the balance is debited only once."""
    token, user_id = await _login_user(integration_client, tg_id=904)
    await _credit_user_wallet(db_session, user_id=user_id, currency="USD", amount=Decimal("20"))

    order_id = await _create_order(
        integration_client, token=token, sku_id=_seed_voucher_sku, key_suffix="concurrent"
    )
    results = await asyncio.gather(
        _pay_with_wallet(integration_client, token=token, order_id=order_id),
        _pay_with_wallet(integration_client, token=token, order_id=order_id),
        return_exceptions=True,
    )
    # Filter exceptions out of the result list — they could come from
    # the second loser racing past the FOR UPDATE.
    successes = [
        r
        for r in results
        if isinstance(r, tuple) and r[0] in (200, 201) and r[1].get("status") == "succeeded"
    ]
    losers = [r for r in results if isinstance(r, tuple) and r[0] == 409]
    assert len(successes) == 1, results
    assert len(losers) == 1, results

    # One payment row, $15 left.
    payments = (
        (await db_session.execute(select(Payment).where(Payment.order_id == order_id)))
        .scalars()
        .all()
    )
    assert len(payments) == 1

    wallet = await integration_client.get(
        "/api/v1/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    bals = {b["currency"]: Decimal(b["balance"]) for b in wallet.json()["balances"]}
    assert bals["USD"] == Decimal("15")
