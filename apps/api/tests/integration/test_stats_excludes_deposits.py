"""A wallet deposit is money moved, not money earned.

``orders`` holds two populations since ADR-0058, and every reporting query but
one counted them together. A deposit that reaches ``delivered`` was summed as
revenue and again when the customer spent the balance on a real order, and it
padded every order count with a row carrying no goods — which drags the
average order value down, since the USD figures correctly value it at zero.
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
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.stats.analytics.business import build_business_analytics
from yupay.modules.stats.schemas import AnalyticsRange
from yupay.modules.stats.service import build_dashboard

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()})


async def _login(client: AsyncClient, tg_id: int) -> str:
    init = _sign(
        {
            "user": json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":")),
            "auth_date": str(int(time.time())),
        }
    )
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def _settled_deposit(client: AsyncClient, *, token: str, amount: str, key: str) -> None:
    created = await client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": amount, "provider": "mock"},
    )
    assert created.status_code == 201, created.text
    payment = created.json()
    hook = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt-{payment['id']}",
                "payment_id": payment["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert hook.status_code == 200, hook.text


async def test_a_deposit_is_not_revenue(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login(integration_client, tg_id=9721)
    await _settled_deposit(
        integration_client, token=token, amount="50000", key="stats-deposit-rev-1"
    )

    dashboard = await build_dashboard(db_session, window_hours=24)
    uzs = [row for row in dashboard.revenue_in_window if row.currency == "UZS"]
    booked = uzs[0].amount if uzs else Decimal("0")
    assert booked == Decimal("0"), (
        f"a 50000 UZS deposit was booked as revenue: {booked}. It is counted again "
        "when the customer spends the balance."
    )


async def test_a_deposit_is_not_an_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    before = await build_dashboard(db_session, window_hours=24)

    token = await _login(integration_client, tg_id=9722)
    await _settled_deposit(
        integration_client, token=token, amount="50000", key="stats-deposit-cnt-1"
    )

    after = await build_dashboard(db_session, window_hours=24)
    assert after.orders_in_window == before.orders_in_window
    assert after.orders_delivered_in_window == before.orders_delivered_in_window
    assert {s.status: s.count for s in after.status_breakdown} == {
        s.status: s.count for s in before.status_breakdown
    }


async def test_a_deposit_does_not_dilute_the_business_funnel(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """AOV is GMV over orders, and a deposit adds only to the denominator."""
    before = await build_business_analytics(db_session, r=AnalyticsRange.D7)

    token = await _login(integration_client, tg_id=9723)
    await _settled_deposit(
        integration_client, token=token, amount="50000", key="stats-deposit-fun-1"
    )

    after = await build_business_analytics(db_session, r=AnalyticsRange.D7)
    assert after.summary.orders == before.summary.orders
    assert after.summary.paid_orders == before.summary.paid_orders
    assert after.summary.delivered_orders == before.summary.delivered_orders
    assert after.summary.aov_usd == before.summary.aov_usd
