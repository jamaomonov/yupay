from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import NotFoundError
from yupay.modules.payments import provider_state as ps
from yupay.modules.payments.models import PaymentProviderState

pytestmark = pytest.mark.asyncio


async def test_default_state_is_active(db_session: AsyncSession) -> None:
    states = await ps.get_states(db_session, ["payme", "uzum"])
    assert states == {"payme": "active", "uzum": "active"}


async def test_set_logical_state_writes_all_slugs(db_session: AsyncSession) -> None:
    await ps.set_logical_state(db_session, provider="click", state="disabled", changed_by=None)
    await db_session.commit()
    states = await ps.get_states(db_session, ["click", "click_miniapp"])
    assert states == {"click": "disabled", "click_miniapp": "disabled"}


async def test_set_logical_state_unknown_provider_raises(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError) as exc_info:
        await ps.set_logical_state(db_session, provider="paypal", state="disabled", changed_by=None)
    assert exc_info.value.extra.get("provider") == "paypal"


async def test_set_logical_state_twice_updates_existing_row_no_duplicate(
    db_session: AsyncSession,
) -> None:
    await ps.set_logical_state(db_session, provider="payme", state="disabled", changed_by=None)
    await db_session.commit()

    await ps.set_logical_state(db_session, provider="payme", state="maintenance", changed_by=None)
    await db_session.commit()

    states = await ps.get_states(db_session, ["payme"])
    assert states == {"payme": "maintenance"}

    rows = (
        (
            await db_session.execute(
                select(PaymentProviderState).where(PaymentProviderState.provider == "payme")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_get_state_default_and_after_set(db_session: AsyncSession) -> None:
    assert await ps.get_state(db_session, "octo") == "active"

    await ps.set_logical_state(db_session, provider="octo", state="disabled", changed_by=None)
    await db_session.commit()

    assert await ps.get_state(db_session, "octo") == "disabled"


def test_state_status_hides_disabled_and_flags_maintenance() -> None:
    assert ps.state_status("disabled") is None
    assert ps.state_status("maintenance") == "maintenance"
    assert ps.state_status("active") == "active"


def test_customer_status_unknown_gateway_hides() -> None:
    assert ps.customer_status("nonexistent-provider", "active") is None


async def test_trip_active_skips_disabled_and_already_maintenance(
    db_session: AsyncSession,
) -> None:
    await ps.set_logical_state(db_session, provider="payme", state="disabled", changed_by=None)
    await ps.set_logical_state(db_session, provider="uzum", state="maintenance", changed_by=None)
    await db_session.commit()

    changed = await ps.trip_active_to_maintenance(db_session)
    await db_session.commit()

    assert "payme" not in changed
    assert "uzum" not in changed
    assert "wallet" in changed
    assert await ps.get_state(db_session, "wallet") == "maintenance"
    assert await ps.get_state(db_session, "payme") == "disabled"
    assert await ps.get_state(db_session, "uzum") == "maintenance"


def test_customer_status_available_gateway_delegates_to_state_status() -> None:
    # "mock" is always config-available under ENVIRONMENT=test (see tests/conftest.py) —
    # it only checks `not is_prod`, so this exercises the "gateway available" branch
    # without depending on any real acquirer's unset keys.
    assert ps.customer_status("mock", "active") == "active"
    assert ps.customer_status("mock", "disabled") is None
