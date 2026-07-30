"""Integration tests for ``POST /api/v1/orders/claim``.

Covers Task 3 of the phase-3 web-orders flow: when a guest registers,
verifies, and logs in with the same email their guest orders were placed
under, ``POST /orders/claim`` migrates those orders onto their account.

- Claiming reassigns matching guest orders (``user_id`` set, ``guest_email``
  nulled) and they show up in ``GET /orders``.
- Claiming is idempotent — a second call claims 0.
- A guest order under a *different* email is never touched.
- ``claim_orders_for_user`` itself refuses (returns 0) for an unverified user
  — exercised directly since an authenticated session always carries a
  verified user (login is gated on verification, Task 1/2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.orders import service as orders_svc
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(id=new_id(), slug="qc-claim", sort_order=1, active=True)
    brand = Brand(
        id=new_id(), slug="qc-claim-brand", category_id=category.id, sort_order=1, active=True
    )
    product = Product(
        id=new_id(),
        slug="qc-claim-product",
        brand_id=brand.id,
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="qc-claim-sku",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _make_guest_order(db_session: AsyncSession, *, guest_email: str, sku_id: str) -> str:
    order = Order(
        id=new_id(),
        guest_email=guest_email,
        status="pending_payment",
        currency="USD",
        total_usd=Decimal("1.50"),
        total_charged=Decimal("1.50"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        items=[
            OrderItem(
                id=new_id(),
                sku_id=sku_id,
                qty=1,
                unit_price_usd=Decimal("1.50"),
                fulfillment_data={},
            )
        ],
    )
    db_session.add(order)
    await db_session.commit()
    return order.id


async def _register_verify_login(
    client: AsyncClient, db_session: AsyncSession, *, email: str
) -> str:
    """Register + verify (auto-login) an account; returns the access token."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "s3cret-passw0rd", "locale": "ru"},
    )
    assert reg.status_code == 201, reg.text

    from yupay.modules.auth import jwt as authjwt

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    token = authjwt.mint_email_verify(sub=user.id)

    verify = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200, verify.text
    access_token: str = verify.json()["access_token"]
    return access_token


async def test_claim_migrates_matching_guest_orders(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    sku_id = await _seed_sku(db_session)
    email = "claim-me@example.com"
    other_email = "not-claimed@example.com"

    mine_order_id = await _make_guest_order(db_session, guest_email=email, sku_id=sku_id)
    other_order_id = await _make_guest_order(db_session, guest_email=other_email, sku_id=sku_id)

    token = await _register_verify_login(integration_client, db_session, email=email)
    headers = {"Authorization": f"Bearer {token}"}

    claim = await integration_client.post("/api/v1/orders/claim", headers=headers)
    assert claim.status_code == 200, claim.text
    assert claim.json() == {"claimed": 1}

    # The order is now owned by the user and cleared of guest_email — the
    # actor-XOR CHECK constraint (ck_orders_actor_exclusive) must still hold.
    db_session.expire_all()
    claimed_order = (
        await db_session.execute(select(Order).where(Order.id == mine_order_id))
    ).scalar_one()
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert claimed_order.user_id == user.id
    assert claimed_order.guest_email is None

    # It now appears in the user's order list.
    listed = await integration_client.get("/api/v1/orders", headers=headers)
    assert listed.status_code == 200, listed.text
    listed_ids = {o["id"] for o in listed.json()["items"]}
    assert mine_order_id in listed_ids

    # A different guest_email order is untouched.
    untouched_order = (
        await db_session.execute(select(Order).where(Order.id == other_order_id))
    ).scalar_one()
    assert untouched_order.user_id is None
    assert untouched_order.guest_email == other_email

    # Idempotent: claiming again finds nothing left to migrate.
    second_claim = await integration_client.post("/api/v1/orders/claim", headers=headers)
    assert second_claim.status_code == 200, second_claim.text
    assert second_claim.json() == {"claimed": 0}


async def test_claim_requires_authentication(integration_client: AsyncClient) -> None:
    r = await integration_client.post("/api/v1/orders/claim")
    assert r.status_code in (401, 403), r.text


async def test_claim_orders_for_user_unverified_claims_nothing(
    db_session: AsyncSession,
) -> None:
    """Direct service-level check: an unverified user's ``email_verified_at``
    is ``None`` (unreachable via the HTTP surface today since login already
    requires verification) — the guard must still return 0, not raise."""
    sku_id = await _seed_sku(db_session)
    email = "unverified-claim@example.com"
    await _make_guest_order(db_session, guest_email=email, sku_id=sku_id)

    user = User(id=new_id(), email=email, password_hash="irrelevant", email_verified_at=None)
    db_session.add(user)
    await db_session.commit()

    count = await orders_svc.claim_orders_for_user(db_session, user=user)
    assert count == 0
