"""``orders.economics`` — the admin order page's purchase cost and margin."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.economics import order_economics
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _sku(db: AsyncSession, product_id: str, code: str, cost: str | None) -> str:
    sku_id = str(uuid.uuid4())
    db.add(
        Sku(
            id=sku_id,
            product_id=product_id,
            sku_code=code,
            denomination=code.upper(),
            price_usd=Decimal("1.00"),
            cost_usdt=None if cost is None else Decimal(cost),
        )
    )
    await db.flush()
    return sku_id


async def _seed(db: AsyncSession) -> tuple[str, str, str]:
    slug = uuid.uuid4().hex[:8]
    user_id, cat, brand, product, order_id = (str(uuid.uuid4()) for _ in range(5))
    db.add(User(id=user_id, email=f"e-{slug}@example.com", locale="ru", roles=[]))
    db.add(Category(id=cat, slug=f"c-{slug}"))
    await db.flush()
    db.add(Brand(id=brand, slug=f"b-{slug}", category_id=cat))
    await db.flush()
    db.add(Product(id=product, slug=f"p-{slug}", brand_id=brand, kind="top_up"))
    await db.flush()
    costed = await _sku(db, product, f"uc-{slug}", "0.80")  # today's price
    unknown = await _sku(db, product, f"pack-{slug}", None)
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            status="delivered",
            currency="USD",
            total_usd=Decimal("3.00"),
            total_charged=Decimal("3.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    db.add_all(
        [
            # Bought at 0.85 a unit (frozen); the supplier is at 0.80 today.
            OrderItem(
                id=a,
                order_id=order_id,
                sku_id=costed,
                qty=2,
                unit_price_usd=Decimal("1.00"),
                cost_usdt=Decimal("0.85"),
            ),
            OrderItem(
                id=b, order_id=order_id, sku_id=unknown, qty=1, unit_price_usd=Decimal("1.00")
            ),
        ]
    )
    await db.flush()
    db.add(
        FulfillmentTask(
            id=str(uuid.uuid4()),
            order_id=order_id,
            order_item_id=a,
            supplier="g2b",
            status="succeeded",
        )
    )
    await db.commit()
    return order_id, a, b


async def test_a_line_shows_what_it_cost_and_what_we_kept(db_session: AsyncSession) -> None:
    order_id, a, b = await _seed(db_session)
    out = await order_economics(db_session, order_id=order_id)

    line = next(x for x in out.lines if x.item_id == a)
    assert line.charged_usd == Decimal("2.00")
    assert line.cost_usd == Decimal("1.70")
    assert line.unit_cost_usd == Decimal("0.8500")
    assert line.cost_source == "frozen"
    assert line.current_unit_cost_usd == Decimal("0.80")
    assert line.margin_usd == Decimal("0.30")
    assert line.margin_pct == Decimal("15.0")
    assert line.supplier == "g2b"

    unknown = next(x for x in out.lines if x.item_id == b)
    assert unknown.cost_usd is None
    assert unknown.margin_usd is None  # an unknown cost is not a 100 % margin

    assert out.charged_usd == Decimal("3.00")
    assert out.margin_usd == Decimal("0.30")
    assert out.cost_usd == Decimal("1.70")
    assert out.margin_pct == Decimal("15.0")
    assert out.unknown_lines == 1
