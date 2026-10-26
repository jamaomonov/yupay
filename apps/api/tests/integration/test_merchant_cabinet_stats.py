"""The cabinet's Statistics screen, as ``GET /merchant/cabinet/stats`` answers it.

The money is aggregated in SQL over the ledger rather than order by order, so
the test that matters is the one the dashboard summary already passes: two
orders, one settled back in full, and a stranger beside them who sees nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id

from tests.integration.cabinet_signup import BASE, capture_cabinet_mail
from tests.integration.cabinet_signup import auth as _auth
from tests.integration.cabinet_signup import signed_up as _signed_up
from tests.integration.test_merchant_cabinet_sections import _credit, _seed_stars

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    return capture_cabinet_mail(monkeypatch)


async def test_stats_count_net_spend_and_rank_brands_for_this_merchant_only(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    mine, my_merchant = await _signed_up(integration_client, sent, "stats@acme.example.com")
    theirs, _ = await _signed_up(integration_client, sent, "stats@other.example.com")
    await _credit(integration_client, admin_headers, my_merchant, "80.00")
    sku_id = _seed_stars(db_session)
    await db_session.commit()

    placed = [
        await integration_client.post(
            f"{BASE}/orders",
            headers=_auth(mine),
            json={"sku_id": sku_id, "quantity": 1000, "expected_price": "16.54"},
        )
        for _ in range(2)
    ]
    assert [r.status_code for r in placed] == [201, 201], placed[0].text
    # Settle one in full, the runbook's way: cancel its task, then credit.
    settled = str(placed[0].json()["order_id"])
    refused = await integration_client.post(
        f"/api/v1/admin/merchants/{my_merchant}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": "16.54", "order_id": settled},
    )
    for task_id in refused.json()["open_task_ids"]:
        await integration_client.post(
            f"/api/v1/admin/fulfillment/tasks/{task_id}/cancel", headers=admin_headers
        )
    await _credit(integration_client, admin_headers, my_merchant, "16.54", order_id=settled)

    since = quote((datetime.now(UTC) - timedelta(hours=24)).isoformat())
    day = await integration_client.get(
        f"{BASE}/stats?since={since}&tz=Asia/Tashkent", headers=_auth(mine)
    )
    ever = await integration_client.get(f"{BASE}/stats?tz=Asia/Tashkent", headers=_auth(mine))
    stranger = await integration_client.get(f"{BASE}/stats?since={since}", headers=_auth(theirs))

    assert day.status_code == 200, day.text
    body = day.json()
    assert body["granularity"] == "hour"
    totals = body["totals"]
    assert totals["orders"] == 2
    assert totals["spend_usd"] == "16.54", "a settled order spent nothing"
    assert totals["refunded_usd"] == "16.54"
    assert totals["avg_order_usd"] == "16.54", "the settled order is not a $0 check"
    assert body["previous"]["orders"] == 0
    assert sum(p["orders"] for p in body["series"]) == 2, "every order lands in a bar"
    assert 24 <= len(body["series"]) <= 26, "the day is cut into hours, gaps filled"
    assert body["brands"] == [
        {
            "brand_name": "Бренд",
            "logo_url": None,
            "orders": 2,
            "delivered": totals["delivered"],
            "failed": totals["failed"],
            "spend_usd": "16.54",
        }
    ]
    assert body["skus"][0]["sku_code"] == "stars-unit"
    assert (body["api_orders"], body["cabinet_orders"]) == (0, 2)

    assert ever.status_code == 200, ever.text
    assert ever.json()["since"] is None
    assert ever.json()["previous"] is None
    assert ever.json()["totals"]["orders"] == 2

    assert stranger.json()["totals"]["orders"] == 0
    assert stranger.json()["brands"] == []


async def test_stats_refuse_an_unknown_zone_and_an_empty_window(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    access, _ = await _signed_up(integration_client, sent, "statsbad@acme.example.com")
    now = datetime.now(UTC)

    zone = await integration_client.get(f"{BASE}/stats?tz=Mars/Olympus", headers=_auth(access))
    future = await integration_client.get(
        f"{BASE}/stats?since={quote((now + timedelta(hours=1)).isoformat())}",
        headers=_auth(access),
    )
    unauth = await integration_client.get(f"{BASE}/stats")

    assert zone.status_code == 422
    assert zone.json()["code"] == "bad_timezone"
    assert future.status_code == 422
    assert future.json()["code"] == "bad_window"
    assert unauth.status_code == 401
