"""The fulfilment state an operator can act on, in the admin DTO (M3c Task 3).

A terminal fulfilment failure deliberately does **not** move ``order.status``:
only the item's ``fulfillment_state`` goes ``failed``, because an operator may
still top a supplier up, retry, or deliver by hand. That is retail's rule and
it stays. Its cost is that the admin list says «В работе» on a dead order for
ever, which is what an owner hit on the first live B2B failure — and
``/merchant/v1`` grew ``failure_reason`` for exactly this while the admin never
did.

So the admin DTO carries the **same** value, from the **same** function
(``merchants.order_status._failure_reason``, batched by ``failure_reasons``)
and the same stall predicate (``fulfillment.stall``). A second spelling in the
admin is how the reseller's answer and the operator's answer would start
disagreeing about one order.

Four states have to render and a healthy order has to render nothing, which is
what this file pins. Note what Task 6 already changed underneath: a *fully
refunded* merchant order now reaches ``failed`` on its own, so the case that
started this is terminal already; what remains showing «В работе» is a
``SPENT``/``UNKNOWN`` park, a partial settlement, and a stall.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
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
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.merchants import deposit
from yupay.modules.merchants.models import Merchant
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ADMIN_ORDERS = "/api/v1/admin/orders"
PRICE = Decimal("1.07")


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 4343, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 4343)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


def _seed_sku(db: AsyncSession) -> str:
    """One category → brand → product → SKU chain; returns the SKU id."""
    tag = new_id()[-8:]
    category = Category(
        id=new_id(),
        slug=f"cat-{tag}",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Категория")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{tag}",
        category_id=category.id,
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Бренд")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{tag}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Продукт")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{tag}",
        denomination="100 UC",
        region="GLOBAL",
        price_usd=Decimal("9.99"),
        cost_usdt=Decimal("1.000000"),
        sort_order=0,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


async def _order(
    db: AsyncSession,
    *,
    status: str = "fulfilling",
    item_state: str = "in_progress",
    merchant_id: str | None = None,
    task_status: str | None = None,
) -> Order:
    """An order with one line, optionally a fulfilment task, and one actor arm."""
    sku_id = _seed_sku(db)
    order = Order(
        id=str(uuid.uuid4()),
        status=status,
        currency="USD",
        total_usd=PRICE,
        total_charged=PRICE,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        merchant_id=merchant_id,
        guest_email=None if merchant_id else "buyer@example.com",
    )
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=PRICE,
        fulfillment_state=item_state,
    )
    db.add_all([order, item])
    # Flushed before the task: the FK is on `orders.id`, and SQLAlchemy has no
    # relationship between the two to order the inserts for us.
    await db.flush()
    if task_status is not None:
        db.add(
            FulfillmentTask(
                id=new_id(),
                order_id=order.id,
                order_item_id=item.id,
                supplier="g2b",
                status=task_status,
            )
        )
    await db.commit()
    return order


async def _merchant(db: AsyncSession, title: str = "Reseller LLC") -> str:
    merchant_id = str(uuid.uuid4())
    db.add(Merchant(id=merchant_id, title=title))
    await db.commit()
    return merchant_id


async def _row(client: AsyncClient, headers: dict[str, str], order_id: str) -> dict[str, Any]:
    r = await client.get(ADMIN_ORDERS, headers=headers)
    assert r.status_code == 200, r.text
    return next(item for item in r.json()["items"] if item["id"] == order_id)


async def _detail(client: AsyncClient, headers: dict[str, str], order_id: str) -> dict[str, Any]:
    r = await client.get(f"{ADMIN_ORDERS}/{order_id}", headers=headers)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


# ---------- the four states ----------


async def test_a_terminally_failed_delivery_says_so_beside_a_status_that_does_not(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The defect, exactly: `fulfilling` for ever with nothing else to read."""
    order = await _order(db_session, item_state="failed")

    row = await _row(integration_client, admin_headers, order.id)

    assert row["status"] == "fulfilling"
    assert row["failure_reason"] == "fulfillment_failed"


async def test_a_stalled_order_reads_as_delayed(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A task that stopped over an item that did not — the supplier-balance shape."""
    order = await _order(db_session, item_state="in_progress", task_status="failed")

    row = await _row(integration_client, admin_headers, order.id)

    assert row["failure_reason"] == "fulfillment_delayed"


async def test_an_order_support_closed_by_hand_reads_as_order_failed(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """`failed` with money outstanding is the hand closure, and says so."""
    order = await _order(db_session, status="failed", item_state="in_progress")

    row = await _row(integration_client, admin_headers, order.id)

    assert row["failure_reason"] == "order_failed"


async def test_a_settled_merchant_order_reads_as_refunded(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The whole charge is back on the deposit — the operator has nothing to do.

    Deliberately the **hand** settlement, because it is the one an operator
    books from this very page, and because it is the value the reseller reads
    at the same moment: one function answers both.
    """
    merchant_id = await _merchant(db_session)
    order = await _order(db_session, item_state="failed", merchant_id=merchant_id)
    await deposit.credit_deposit(
        db_session,
        merchant_id=merchant_id,
        amount=Decimal("10.00"),
        actor="test",
        idempotency_key=f"fund-{new_id()}",
        order_id=None,
    )
    await deposit.charge_deposit(
        db_session, merchant_id=merchant_id, amount=PRICE, order_id=order.id
    )
    await deposit.credit_deposit(
        db_session,
        merchant_id=merchant_id,
        amount=PRICE,
        actor="admin:test",
        idempotency_key=f"settle-{new_id()}",
        order_id=order.id,
    )
    await db_session.commit()

    row = await _row(integration_client, admin_headers, order.id)

    assert row["failure_reason"] == "fulfillment_failed_refunded"


async def test_a_partly_settled_merchant_order_still_needs_a_human(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A sum is not a flag: one cent back is a person mid-decision, not a refund."""
    merchant_id = await _merchant(db_session)
    order = await _order(db_session, item_state="failed", merchant_id=merchant_id)
    await deposit.credit_deposit(
        db_session,
        merchant_id=merchant_id,
        amount=Decimal("10.00"),
        actor="test",
        idempotency_key=f"fund-{new_id()}",
        order_id=None,
    )
    await deposit.charge_deposit(
        db_session, merchant_id=merchant_id, amount=PRICE, order_id=order.id
    )
    await deposit.credit_deposit(
        db_session,
        merchant_id=merchant_id,
        amount=Decimal("0.01"),
        actor="admin:test",
        idempotency_key=f"part-{new_id()}",
        order_id=order.id,
    )
    await db_session.commit()

    row = await _row(integration_client, admin_headers, order.id)

    assert row["failure_reason"] == "fulfillment_failed"


async def test_a_healthy_in_flight_order_says_nothing_extra(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The value must stay quiet, or every order on the page grows a warning."""
    order = await _order(db_session, item_state="in_progress", task_status="in_progress")

    row = await _row(integration_client, admin_headers, order.id)

    assert row["failure_reason"] is None


async def test_a_delivered_order_says_nothing_extra(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Nothing failed and nothing stopped — and the stall read is skipped."""
    order = await _order(db_session, status="delivered", item_state="delivered")

    row = await _row(integration_client, admin_headers, order.id)

    assert row["failure_reason"] is None


async def test_the_detail_page_carries_it_too(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Both surfaces: the list is where it is spotted, the detail where it is acted on."""
    order = await _order(db_session, item_state="failed")

    body = await _detail(integration_client, admin_headers, order.id)

    assert body["failure_reason"] == "fulfillment_failed"


async def test_one_orders_stall_does_not_delay_the_order_beside_it(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The batched read must stay scoped, or a page turns one stall into fifty.

    The single-order predicate cannot make this mistake; a batch can, which is
    exactly why it is pinned here rather than trusted.
    """
    stalled = await _order(db_session, item_state="in_progress", task_status="failed")
    healthy = await _order(db_session, item_state="in_progress", task_status="in_progress")

    assert (await _row(integration_client, admin_headers, stalled.id))["failure_reason"] == (
        "fulfillment_delayed"
    )
    assert (await _row(integration_client, admin_headers, healthy.id))["failure_reason"] is None


# ---------- M3c Task 4: the deposit numbers an operator settles from ----------


async def test_a_merchant_order_says_what_its_deposit_did(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A merchant order has no `Payment` row, so «Платежи (0)» was the whole story.

    The money is on the deposit ledger, and until M3c Task 4 the operator's
    page said nothing about it — which is why the settle affordance was on the
    merchant's page and the operator was standing somewhere else.
    """
    merchant_id = await _merchant(db_session)
    order = await _order(db_session, item_state="failed", merchant_id=merchant_id)
    await deposit.credit_deposit(
        db_session,
        merchant_id=merchant_id,
        amount=Decimal("10.00"),
        actor="test",
        idempotency_key=f"fund-{new_id()}",
        order_id=None,
    )
    await deposit.charge_deposit(
        db_session, merchant_id=merchant_id, amount=PRICE, order_id=order.id
    )
    await db_session.commit()

    row = await _row(integration_client, admin_headers, order.id)

    assert Decimal(row["deposit_charged_usd"]) == PRICE
    assert Decimal(row["deposit_returned_usd"]) == Decimal("0")


async def test_a_retail_order_has_no_deposit_numbers_at_all(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """`None`, not zero — the button reads it as "there is nothing to settle here".

    A retail order's money is at an acquirer and is reversed through
    `payments.refund_admin`; a deposit charge of `0` would be a claim that one
    exists and came to nothing.
    """
    order = await _order(db_session, item_state="failed")

    row = await _row(integration_client, admin_headers, order.id)

    assert row["deposit_charged_usd"] is None
    assert Decimal(row["deposit_returned_usd"]) == Decimal("0")
