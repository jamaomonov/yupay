"""The admin order view's third actor arm (M3c Task 2).

``orders`` has had three actor arms since M2 — user, guest, merchant, kept
exclusive by ``ck_orders_actor_exclusive`` — and the admin surface had two.
A merchant order therefore reached an operator as ``guest_email = null``,
which the SPA rendered as «Гость»: the one class of order whose owner is
never in doubt read as the one class whose owner is anonymous. The only trace
was a raw uuid in a timeline payload.

The DTO carries the merchant's **title** beside the id on purpose. An
operator recognises "Reseller LLC"; nobody recognises
``0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34``, and a second round-trip to look it
up is what the list already does for users and what the merchant page is for.

Both surfaces are covered — the list and the detail — because the defect was
on both, and the two retail arms are pinned unchanged so "adds a third arm"
cannot quietly become "changes the other two".
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
from yupay.modules.merchants.models import Merchant
from yupay.modules.orders.models import Order
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ADMIN_ORDERS = "/api/v1/admin/orders"


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
    user_json = json.dumps({"id": 4242, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 4242)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _merchant(db: AsyncSession, title: str) -> str:
    merchant_id = str(uuid.uuid4())
    db.add(Merchant(id=merchant_id, title=title))
    await db.flush()
    return merchant_id


async def _buyer(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id[:8]}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()
    return user_id


def _order(**actor: str | None) -> Order:
    """One order with the given actor column set and neutral money fields."""
    return Order(
        id=str(uuid.uuid4()),
        status="fulfilling",
        currency="USD",
        total_usd=Decimal("1.07"),
        total_charged=Decimal("1.07"),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        **actor,
    )


async def _row(client: AsyncClient, headers: dict[str, str], order_id: str) -> dict[str, Any]:
    """That order's row out of the admin listing."""
    r = await client.get(ADMIN_ORDERS, headers=headers)
    assert r.status_code == 200, r.text
    return next(item for item in r.json()["items"] if item["id"] == order_id)


async def _detail(client: AsyncClient, headers: dict[str, str], order_id: str) -> dict[str, Any]:
    r = await client.get(f"{ADMIN_ORDERS}/{order_id}", headers=headers)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_a_merchant_order_names_the_merchant_in_the_list(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The list is where an operator meets the order, so it is where the lie was."""
    merchant_id = await _merchant(db_session, "Reseller LLC")
    order = _order(merchant_id=merchant_id)
    db_session.add(order)
    await db_session.commit()

    row = await _row(integration_client, admin_headers, order.id)

    assert row["merchant_id"] == merchant_id
    assert row["merchant_title"] == "Reseller LLC"
    assert row["user_id"] is None
    assert row["guest_email"] is None


async def test_a_merchant_order_names_the_merchant_on_the_detail(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Both surfaces, because the «Гость» line was on both."""
    merchant_id = await _merchant(db_session, "Другой реселлер")
    order = _order(merchant_id=merchant_id)
    db_session.add(order)
    await db_session.commit()

    body = await _detail(integration_client, admin_headers, order.id)

    assert body["merchant_id"] == merchant_id
    assert body["merchant_title"] == "Другой реселлер"


async def test_a_guest_order_is_unchanged(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The arm that used to absorb every merchant order still reads as itself."""
    order = _order(guest_email="buyer@example.com")
    db_session.add(order)
    await db_session.commit()

    row = await _row(integration_client, admin_headers, order.id)

    assert row["guest_email"] == "buyer@example.com"
    assert row["merchant_id"] is None
    assert row["merchant_title"] is None


async def test_a_user_order_is_unchanged(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The third arm is additive: a signed-in buyer's order gains nothing."""
    user_id = await _buyer(db_session)
    order = _order(user_id=user_id)
    db_session.add(order)
    await db_session.commit()

    row = await _row(integration_client, admin_headers, order.id)

    assert row["user_id"] == user_id
    assert row["merchant_id"] is None
    assert row["merchant_title"] is None


async def test_two_merchants_on_one_page_are_not_confused(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The titles are read in one batched query — so pin the mapping, not the count.

    A batch keyed on the wrong side (or a ``dict`` built from the last row
    seen) shows every reseller the same name, which is worse than showing
    none: an operator would act on it.
    """
    one = await _merchant(db_session, "Alpha")
    two = await _merchant(db_session, "Beta")
    first = _order(merchant_id=one)
    second = _order(merchant_id=two)
    db_session.add_all([first, second])
    await db_session.commit()

    assert (await _row(integration_client, admin_headers, first.id))["merchant_title"] == "Alpha"
    assert (await _row(integration_client, admin_headers, second.id))["merchant_title"] == "Beta"
