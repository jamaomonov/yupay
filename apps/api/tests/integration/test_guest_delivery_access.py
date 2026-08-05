"""Guest access to delivered codes requires an order-scoped magic-link token.

The freely-mintable email-only guest token (``POST /auth/guest``) must no longer
unlock ``GET /orders/{id}/deliveries`` — otherwise anyone who knows a buyer's
email can mint a token and read their delivered codes (audit #1, an IDOR on
bearer instruments). Only a ``guest_order`` token bound to *that* order_id (minted
server-side and delivered via the order's email) grants code access.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.fulfillment.models import Delivery
from yupay.modules.orders.models import Order, OrderItem

pytestmark = pytest.mark.asyncio

GUEST_EMAIL = "buyer@yupay.test"
CODE = "SECRET-CODE-XYZ"


async def _seed_delivered_guest_order(db: AsyncSession) -> str:
    """A delivered guest order carrying one voucher code. Returns order_id."""
    category = Category(
        id=new_id(),
        slug="games-gda",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="cs2-gda",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="CS2")],
    )
    product = Product(
        id=new_id(),
        slug="cs2-coins-gda",
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
        sku_code="cs2-100-gda",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("0.99"),
        sort_order=10,
        active=True,
    )
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=GUEST_EMAIL,
        status="delivered",
        currency="USD",
        total_usd=Decimal("0.99"),
        total_charged=Decimal("0.99"),
        expires_at=now() + timedelta(hours=1),
    )
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku.id,
        qty=1,
        unit_price_usd=Decimal("0.99"),
        fulfillment_state="delivered",
    )
    delivery = Delivery(
        id=new_id(),
        order_item_id=item.id,
        channel="in_app",
        artifact_kind="voucher_code",
        artifact={"code": CODE},
    )
    db.add_all([category, brand, product, sku, order, item])
    await db.flush()  # parents before the delivery FK
    db.add(delivery)
    await db.commit()
    return order.id


def _guest_headers(token: str, email: str = GUEST_EMAIL) -> dict[str, str]:
    return {"Authorization": f"Guest {token}", "X-Guest-Email": email}


async def test_email_only_guest_token_cannot_read_codes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The freely-mintable checkout guest token no longer unlocks codes."""
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    stale = authjwt.mint_guest(email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries", headers=_guest_headers(stale)
    )
    assert r.status_code == 401, r.text


async def test_order_scoped_token_reads_its_own_codes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    token = authjwt.mint_guest_order(order_id=order_id, email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries", headers=_guest_headers(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [d.get("artifact", {}).get("code") for d in body["items"]]
    assert CODE in codes


async def test_token_for_another_order_is_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A guest_order token bound to a different order must not unlock this one."""
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    other = authjwt.mint_guest_order(order_id="some-other-order", email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries", headers=_guest_headers(other)
    )
    assert r.status_code in (401, 404), r.text


async def test_email_mismatch_is_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    token = authjwt.mint_guest_order(order_id=order_id, email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers=_guest_headers(token, email="attacker@yupay.test"),
    )
    assert r.status_code == 401, r.text
