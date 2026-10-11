"""An account's lifetime purchase limit and the trusted flag (orders.account_policy)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.modules.orders import account_policy
from yupay.modules.orders.models import Order
from yupay.modules.orders.risk import (
    REASON_LARGE_AMOUNT,
    REASON_PURCHASE_LIMIT,
    _is_trusted_buyer,
    review_reason,
)
from yupay.modules.users.models import User
from yupay.modules.users.service import set_purchase_policy

from tests.integration.test_user_ban import _grant_admin, _login, _user_id

pytestmark = pytest.mark.asyncio


def _cfg() -> Settings:
    base = get_settings().model_dump()
    base.update(
        manual_review_threshold_usd=Decimal("40"),
        risk_jitter=False,
        risk_sum_24h_usd=Decimal("0"),
        risk_sum_7d_usd=Decimal("0"),
        risk_velocity_24h=0,
        risk_distinct_buyers_7d=0,
    )
    return Settings(**base)


async def _user(db: AsyncSession, *, limit: str | None = None, trusted: bool = False) -> User:
    user = User(
        id=new_id(),
        email=f"buyer-{new_id()}@example.test",
        purchase_limit_usd=Decimal(limit) if limit is not None else None,
        trusted_at=now() if trusted else None,
    )
    db.add(user)
    await db.flush()
    return user


async def _order(
    db: AsyncSession,
    total: str,
    *,
    user: User | None = None,
    guest_email: str | None = None,
    status: str = "paid",
) -> Order:
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user.id if user else None,
        guest_email=guest_email,
        status=status,
        currency="USD",
        total_usd=Decimal(total),
        total_charged=Decimal(total),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment,
    )
    db.add(order)
    await db.flush()
    return order


async def test_one_order_over_the_limit_is_held(db_session: AsyncSession) -> None:
    user = await _user(db_session, limit="30")
    order = await _order(db_session, "31", user=user)
    assert await review_reason(db_session, order, settings=_cfg()) == REASON_PURCHASE_LIMIT


async def test_cheap_orders_add_up_to_the_limit(db_session: AsyncSession) -> None:
    user = await _user(db_session, limit="30")
    for _ in range(2):
        await _order(db_session, "10", user=user, status="delivered")
    third = await _order(db_session, "10", user=user)
    assert await review_reason(db_session, third, settings=_cfg()) is None
    third.status = "delivered"
    fourth = await _order(db_session, "10", user=user)
    assert await review_reason(db_session, fourth, settings=_cfg()) == REASON_PURCHASE_LIMIT


async def test_refunded_orders_do_not_count(db_session: AsyncSession) -> None:
    user = await _user(db_session, limit="30")
    await _order(db_session, "25", user=user, status="refunded")
    await _order(db_session, "25", user=user, status="failed")
    order = await _order(db_session, "25", user=user)
    assert await review_reason(db_session, order, settings=_cfg()) is None


async def test_guest_orders_under_the_account_email_count(db_session: AsyncSession) -> None:
    user = await _user(db_session, limit="30")
    assert user.email is not None
    await _order(db_session, "20", guest_email=user.email, status="delivered")
    order = await _order(db_session, "15", guest_email=user.email.upper())
    assert await review_reason(db_session, order, settings=_cfg()) == REASON_PURCHASE_LIMIT


async def test_a_trusted_account_skips_every_rule(db_session: AsyncSession) -> None:
    user = await _user(db_session, limit="10", trusted=True)
    order = await _order(db_session, "500", user=user)
    assert await review_reason(db_session, order, settings=_cfg()) is None
    assert await _is_trusted_buyer(db_session, user.id)


async def test_no_policy_keeps_the_standard_rules(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    order = await _order(db_session, "50", user=user)
    assert await review_reason(db_session, order, settings=_cfg()) == REASON_LARGE_AMOUNT
    guest = await _order(db_session, "5", guest_email="nobody@example.test")
    assert await account_policy.policy_for(db_session, guest) == account_policy.NO_POLICY


async def test_set_purchase_policy_keeps_the_first_trusted_stamp(
    db_session: AsyncSession,
) -> None:
    admin = await _user(db_session)
    user = await _user(db_session)
    await set_purchase_policy(
        db_session, user.id, by_admin_id=admin.id, trusted=True, purchase_limit_usd=None
    )
    first = user.trusted_at
    await set_purchase_policy(
        db_session, user.id, by_admin_id=admin.id, trusted=True, purchase_limit_usd=Decimal("30")
    )
    assert user.trusted_at == first
    assert user.trusted_by == admin.id
    await set_purchase_policy(
        db_session, user.id, by_admin_id=admin.id, trusted=False, purchase_limit_usd=None
    )
    assert (user.trusted_at, user.trusted_by, user.purchase_limit_usd) == (None, None, None)


async def test_the_admin_route_round_trip(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(integration_client, tg_id=7301)
    buyer_id = await _user_id(db_session, 7301)
    await _login(integration_client, tg_id=7302)
    await _grant_admin(db_session, 7302)
    auth = {"Authorization": f"Bearer {await _login(integration_client, tg_id=7302)}"}
    url = f"/api/v1/admin/users/{buyer_id}/purchase-policy"

    r = await integration_client.put(
        url, headers=auth, json={"trusted": True, "purchase_limit_usd": "30"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["trusted_at"] is not None
    assert Decimal(r.json()["purchase_limit_usd"]) == Decimal("30")

    off = await integration_client.put(
        url, headers=auth, json={"trusted": False, "purchase_limit_usd": None}
    )
    assert (off.json()["trusted_at"], off.json()["purchase_limit_usd"]) == (None, None)

    bad = await integration_client.put(
        url, headers=auth, json={"trusted": False, "purchase_limit_usd": "-1"}
    )
    assert bad.status_code == 422

    plain = {"Authorization": f"Bearer {await _login(integration_client, tg_id=7301)}"}
    denied = await integration_client.put(
        url, headers=plain, json={"trusted": True, "purchase_limit_usd": None}
    )
    assert denied.status_code == 403
