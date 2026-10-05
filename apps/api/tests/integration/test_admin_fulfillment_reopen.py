"""``POST /admin/fulfillment/tasks/{id}/reopen`` — a cancelled task back into the inbox.

Pins the one transition «Отменить» had no way back from: cancelled → failed,
where Retry / Reassign / manual completion apply again. Refused for anything
not cancelled, and for an order that is no longer deliverable.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.fulfillment.models import FulfillmentAttempt, FulfillmentTask
from yupay.modules.orders.models import Order

from tests.integration.test_admin_fulfillment_bulk_routes import _admin_headers, _make_task

pytestmark = pytest.mark.asyncio

__all__ = ["_admin_headers"]


async def test_reopen_turns_a_cancelled_task_into_a_failed_one(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    task_id = await _make_task(db_session, status="cancelled", supplier="fzr")

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reopen", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"

    db_session.expire_all()
    task = await db_session.get(FulfillmentTask, task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.failed_at is not None
    assert task.cancelled_at is None
    kinds = (
        await db_session.execute(
            select(FulfillmentAttempt.kind).where(FulfillmentAttempt.task_id == task_id)
        )
    ).scalars()
    assert "reopen" in list(kinds)

    # Now retryable — the whole point. (fzr with no key fails the run, which
    # is fine: the button worked, the supplier is a separate matter.)
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/retry", headers=_admin_headers
    )
    assert r.status_code == 200, r.text


async def test_reopen_refuses_a_task_that_was_not_cancelled(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    task_id = await _make_task(db_session, status="failed")
    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reopen", headers=_admin_headers
    )
    assert r.status_code == 409, r.text


async def test_reopen_refuses_an_order_that_is_no_longer_deliverable(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    task_id = await _make_task(db_session, status="cancelled")
    task = await db_session.get(FulfillmentTask, task_id)
    assert task is not None
    order = await db_session.get(Order, task.order_id)
    assert order is not None
    order.status = "refunded"
    await db_session.commit()

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{task_id}/reopen", headers=_admin_headers
    )
    assert r.status_code == 409, r.text
    assert "no longer deliverable" in r.text


async def test_reopen_requires_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.post("/api/v1/admin/fulfillment/tasks/x/reopen")
    assert r.status_code == 401
