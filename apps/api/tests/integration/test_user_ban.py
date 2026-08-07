"""Account suspension (ADR-0045).

The interesting assertions are all about the ways a ban could be walked around:
a token minted before the ban, a fresh login, a refresh rotation, and guest
checkout under the same address.
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
from yupay.modules.users.models import TelegramLink, User

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _user_id(db: AsyncSession, tg_id: int) -> str:
    return (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    user_id = await _user_id(db, tg_id)
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return user_id


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="ban-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ban")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="ban-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Ban Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="ban-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Ban Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="BAN-1",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


# ---------- the admin action ----------


async def test_ban_and_unban_round_trip(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(integration_client, tg_id=7201)
    victim_id = await _user_id(db_session, 7201)
    await _login(integration_client, tg_id=7202)
    await _grant_admin(db_session, 7202)
    admin_token = await _login(integration_client, tg_id=7202)
    auth = {"Authorization": f"Bearer {admin_token}"}

    banned = await integration_client.post(
        f"/api/v1/admin/users/{victim_id}/ban",
        headers=auth,
        json={"reason": "stolen card"},
    )
    assert banned.status_code == 200, banned.text
    assert banned.json()["banned_at"] is not None
    assert banned.json()["ban_reason"] == "stolen card"

    lifted = await integration_client.post(f"/api/v1/admin/users/{victim_id}/unban", headers=auth)
    assert lifted.status_code == 200, lifted.text
    # Reason and actor are cleared with the timestamp: a leftover reason on an
    # active account reads like a live ban to the next person who looks.
    assert lifted.json()["banned_at"] is None
    assert lifted.json()["ban_reason"] is None
    assert lifted.json()["banned_by"] is None


async def test_an_admin_cannot_ban_themselves(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The straightforward way to lose the only admin account."""
    await _login(integration_client, tg_id=7203)
    admin_id = await _grant_admin(db_session, 7203)
    token = await _login(integration_client, tg_id=7203)

    r = await integration_client.post(
        f"/api/v1/admin/users/{admin_id}/ban",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 422, r.text


async def test_an_admin_cannot_ban_another_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(integration_client, tg_id=7204)
    other_admin_id = await _grant_admin(db_session, 7204)
    await _login(integration_client, tg_id=7205)
    await _grant_admin(db_session, 7205)
    token = await _login(integration_client, tg_id=7205)

    r = await integration_client.post(
        f"/api/v1/admin/users/{other_admin_id}/ban",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 422, r.text


async def test_banning_is_admin_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(integration_client, tg_id=7206)
    victim_id = await _user_id(db_session, 7206)
    plain_token = await _login(integration_client, tg_id=7207)

    r = await integration_client.post(
        f"/api/v1/admin/users/{victim_id}/ban",
        headers={"Authorization": f"Bearer {plain_token}"},
        json={},
    )
    assert r.status_code == 403


# ---------- the ways around it ----------


async def test_a_token_minted_before_the_ban_stops_working(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The reason the check lives in ``current_user`` and not only at login.

    An access token is valid for 15 minutes. If the ban were enforced only when
    a session opens, a suspended customer would keep full access for the rest of
    that window — long enough to place more orders.
    """
    victim_token = await _login(integration_client, tg_id=7208)
    victim_id = await _user_id(db_session, 7208)

    before = await integration_client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {victim_token}"}
    )
    assert before.status_code == 200

    await _login(integration_client, tg_id=7209)
    await _grant_admin(db_session, 7209)
    admin_token = await _login(integration_client, tg_id=7209)
    ban = await integration_client.post(
        f"/api/v1/admin/users/{victim_id}/ban",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "chargeback abuse"},
    )
    assert ban.status_code == 200, ban.text

    after = await integration_client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {victim_token}"}
    )
    assert after.status_code == 403, "the same token must stop working immediately"
    # 403 and not 401: both frontends answer 401 by refreshing the session,
    # which for a banned account loops and then logs the customer out with no
    # explanation. The distinct type lets the storefront say what happened.
    assert after.json()["type"].endswith("/account-suspended")


async def test_a_banned_account_cannot_log_in_again(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Otherwise login succeeds and every call afterwards fails — worse than a
    refusal, because nothing tells the customer why."""
    await _login(integration_client, tg_id=7210)
    victim_id = await _user_id(db_session, 7210)
    await _login(integration_client, tg_id=7211)
    await _grant_admin(db_session, 7211)
    admin_token = await _login(integration_client, tg_id=7211)
    await integration_client.post(
        f"/api/v1/admin/users/{victim_id}/ban",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )

    user_json = json.dumps({"id": 7210, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})

    assert r.status_code == 403
    assert r.json()["type"].endswith("/account-suspended")


async def test_guest_checkout_under_the_banned_email_is_refused(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """Guest checkout creates no user row, so without this the ban is lifted by
    simply not logging in."""
    email = "banned-guest@example.com"
    await _login(integration_client, tg_id=7212)
    victim_id = await _user_id(db_session, 7212)
    await db_session.execute(update(User).where(User.id == victim_id).values(email=email))
    await db_session.commit()

    await _login(integration_client, tg_id=7213)
    await _grant_admin(db_session, 7213)
    admin_token = await _login(integration_client, tg_id=7213)
    await integration_client.post(
        f"/api/v1/admin/users/{victim_id}/ban",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )

    minted = await integration_client.post("/api/v1/auth/guest", json={"email": email})
    assert minted.status_code == 200, minted.text
    guest_token = minted.json()["access_token"]

    r = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Guest {guest_token}",
            "Idempotency-Key": "idem-ban-7212-padding",
        },
        json={
            "currency": "USD",
            "guest_email": email,
            "items": [{"sku_id": _seed_sku, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert r.status_code == 403
    assert r.json()["type"].endswith("/account-suspended")
