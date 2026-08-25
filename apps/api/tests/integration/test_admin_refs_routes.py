"""Display data for ids the panel already holds.

The admin linked to profiles and orders by raw UUID in fifteen places. An id is
not something an operator recognises, and widening fifteen DTOs to carry a name
and a picture — then keeping their joins in step — is the version of this that
rots. One endpoint resolves them instead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
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
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

from tests.integration.test_admin_customer_overview_routes import _grant_admin, _login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Declared here rather than imported: importing a fixture shadows the name
    in every test that also takes it as an argument, which ruff reads as a
    redefinition and which hides which fixture is actually in play."""
    token = await _login(integration_client, tg_id=4242)
    await _grant_admin(db_session, tg_id=4242)
    return {"Authorization": f"Bearer {token}"}


async def _seed_order(db: AsyncSession, *, sku_image: str | None) -> tuple[str, str]:
    """A one-line order. Returns ``(order_id, user_id)``."""
    suffix = new_id()[:8]
    cat = Category(id=new_id(), slug=f"c-{suffix}", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug=f"b-{suffix}", category_id=cat.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name="Свободный Огонь")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug=f"p-{suffix}", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="P")]
    db.add(product)
    await db.flush()
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"s-{suffix}",
        denomination="110 Diamonds",
        price_usd=Decimal("1.00"),
        image_url=sku_image,
    )
    db.add(sku)
    user = User(id=new_id(), email="buyer@example.com", display_name="Дарья", locale="ru")
    db.add(user)
    await db.flush()
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user.id,
        guest_email=None,
        status="delivered",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        expires_at=moment,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku.id,
            qty=1,
            unit_price_usd=Decimal("1.00"),
        )
    )
    await db.commit()
    return str(order.id), str(user.id)


async def test_a_user_id_resolves_to_a_face_and_a_name(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    _, user_id = await _seed_order(db_session, sku_image=None)
    r = await integration_client.get(f"/api/v1/admin/refs?users={user_id}", headers=_admin_headers)
    assert r.status_code == 200, r.text
    row = r.json()["users"][0]
    assert row["id"] == user_id
    assert row["name"] == "Дарья"


async def test_a_nameless_account_falls_back_to_its_login_email(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    """A row still has to be readable when nobody set a display name."""
    user = User(id=new_id(), email="nameless@example.com", display_name=None, locale="ru")
    db_session.add(user)
    await db_session.commit()
    r = await integration_client.get(f"/api/v1/admin/refs?users={user.id}", headers=_admin_headers)
    assert r.json()["users"][0]["name"] == "nameless@example.com"


async def test_an_order_id_resolves_to_what_was_in_it(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    """The artwork of the first line is what an operator remembers about an order."""
    order_id, _ = await _seed_order(db_session, sku_image="https://cdn.example/ff.png")
    r = await integration_client.get(
        f"/api/v1/admin/refs?orders={order_id}", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    row = r.json()["orders"][0]
    assert row["id"] == order_id
    assert row["image_url"] == "https://cdn.example/ff.png"
    assert row["label"] == "Свободный Огонь · 110 Diamonds"


async def test_an_unknown_id_is_absent_rather_than_an_error(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A deleted user or a purged order is exactly the kind of row an admin page
    still has to render — failing the whole lookup would blank the page."""
    r = await integration_client.get(
        f"/api/v1/admin/refs?users={uuid.uuid4()}&orders={uuid.uuid4()}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"users": [], "orders": []}


async def test_it_is_admin_only(integration_client: AsyncClient) -> None:
    """It exposes names and emails; anonymous callers get nothing."""
    r = await integration_client.get("/api/v1/admin/refs")
    assert r.status_code in (401, 403), r.text
