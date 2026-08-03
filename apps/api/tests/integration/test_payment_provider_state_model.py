from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.modules.payments.models import PaymentProviderState

pytestmark = pytest.mark.asyncio


async def test_provider_state_row_roundtrips(db_session: AsyncSession) -> None:
    db_session.add(
        PaymentProviderState(
            provider="payme", state="maintenance", changed_by=None, changed_at=now()
        )
    )
    await db_session.commit()
    row = (
        await db_session.execute(
            select(PaymentProviderState).where(PaymentProviderState.provider == "payme")
        )
    ).scalar_one()
    assert row.state == "maintenance"
