from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


async def test_invalid_state_rejected_by_check_constraint(db_session: AsyncSession) -> None:
    """The ``ck_payment_provider_states_state`` CHECK must reject unknown states.

    Proves the constraint actually restricts ``state`` to
    active/disabled/maintenance rather than merely trusting the migration's
    SQL string was typed correctly.
    """
    db_session.add(
        PaymentProviderState(provider="payme", state="bogus", changed_by=None, changed_at=now())
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
