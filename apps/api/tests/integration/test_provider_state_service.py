from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import NotFoundError
from yupay.modules.payments import provider_state as ps

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
    with pytest.raises(NotFoundError):
        await ps.set_logical_state(db_session, provider="paypal", state="disabled", changed_by=None)


def test_state_status_hides_disabled_and_flags_maintenance() -> None:
    assert ps.state_status("disabled") is None
    assert ps.state_status("maintenance") == "maintenance"
    assert ps.state_status("active") == "active"
