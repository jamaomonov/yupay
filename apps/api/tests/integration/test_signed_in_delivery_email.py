"""A signed-in buyer gets their codes emailed too.

Checkout has always shown a required email field to everyone. For a signed-in
customer the value was dropped on the client and, had it arrived, there was
nowhere to put it: ``guest_email`` is half of ``ck_orders_actor_exclusive`` and
must stay NULL on a signed-in order. So the notification, which read
``order.guest_email`` alone, mailed nothing. On prod that was 107 delivered
orders, 36 of them belonging to accounts with a perfectly good address on file.
Telegram covered whoever had linked a chat and silently did not cover the rest.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import get_settings
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
from yupay.modules.fulfillment.models import Delivery
from yupay.modules.notifications.service import notify_order_delivered
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

CODE = "SIGNED-IN-CODE-1"


async def _seed(
    db: AsyncSession,
    *,
    login_email: str | None,
    user_delivery: str | None = None,
    order_delivery: str | None = None,
) -> str:
    suffix = new_id()[:8]
    category = Category(
        id=new_id(),
        slug=f"c-{suffix}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"b-{suffix}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="B")],
    )
    product = Product(
        id=new_id(),
        slug=f"p-{suffix}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="P")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"s-{suffix}",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("0.99"),
        sort_order=10,
        active=True,
    )
    user = User(
        id=new_id(),
        email=login_email,
        delivery_email=user_delivery,
        locale="ru",
        display_currency="USD",
    )
    order = Order(
        id=new_id(),
        user_id=user.id,
        guest_email=None,
        delivery_email=order_delivery,
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
    # The user first: ``order.user_id`` is assigned in Python, so SQLAlchemy
    # cannot infer the FK ordering from the objects alone.
    db.add(user)
    await db.flush()
    db.add_all([category, brand, product, sku, order, item])
    await db.flush()
    db.add(
        Delivery(
            id=new_id(),
            order_item_id=item.id,
            channel="in_app",
            artifact_kind="voucher_code",
            artifact={"code": CODE},
        )
    )
    await db.commit()
    return str(order.id)


@pytest.fixture
def _mail(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, str]]]:
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append({"to": to, "html": html})
        return "m"

    monkeypatch.setattr("yupay.modules.notifications.service.send_email", _spy, raising=False)
    monkeypatch.setenv("WEB_BASE_URL", "https://yupay.uz/ru")
    get_settings.cache_clear()
    yield sent
    get_settings.cache_clear()


async def test_the_address_typed_at_checkout_wins(
    db_session: AsyncSession,
    _mail: list[dict[str, str]],
    integration_client: AsyncClient,
) -> None:
    """What the buyer asked for on this order beats every default."""
    order_id = await _seed(
        db_session,
        login_email="login@example.com",
        user_delivery="default@example.com",
        order_delivery="this-order@example.com",
    )
    await notify_order_delivered(order_id)
    assert [m["to"] for m in _mail] == ["this-order@example.com"]
    assert CODE in _mail[0]["html"]


async def test_the_account_default_is_used_when_the_order_names_none(
    db_session: AsyncSession,
    _mail: list[dict[str, str]],
    integration_client: AsyncClient,
) -> None:
    """What the mini app's settings screen writes."""
    order_id = await _seed(
        db_session, login_email="login@example.com", user_delivery="default@example.com"
    )
    await notify_order_delivered(order_id)
    assert [m["to"] for m in _mail] == ["default@example.com"]


async def test_the_login_address_is_the_last_resort(
    db_session: AsyncSession,
    _mail: list[dict[str, str]],
    integration_client: AsyncClient,
) -> None:
    """The 36 prod orders that had an address all along and were never mailed."""
    order_id = await _seed(db_session, login_email="login@example.com")
    await notify_order_delivered(order_id)
    assert [m["to"] for m in _mail] == ["login@example.com"]


async def test_a_telegram_only_account_with_no_address_is_not_mailed(
    db_session: AsyncSession,
    _mail: list[dict[str, str]],
    integration_client: AsyncClient,
) -> None:
    """No address is not an error, and must not become a send to nowhere."""
    order_id = await _seed(db_session, login_email=None)
    await notify_order_delivered(order_id)
    assert _mail == []
