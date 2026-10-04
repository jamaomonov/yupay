"""Reservation edge paths: rate gate, stale holds, cancel of an overdue one, a lost race."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.errors import AppError
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.models import P2PReservation
from yupay.modules.pricing.fx_guard import RateRejected

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    _card,
    _code,
    _fixed_rate,
    _merchant,
    _open,
)

pytestmark = pytest.mark.asyncio


async def _overdue(db: AsyncSession, r: P2PReservation) -> None:
    await db.execute(
        update(P2PReservation)
        .where(P2PReservation.id == r.id)
        .values(expires_at=now() - timedelta(seconds=1))
    )
    await db.refresh(r)


async def test_a_rejected_rate_is_fx_unavailable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])

    async def _reject(db: AsyncSession, *, quote: str, override_cache: object = None) -> Decimal:
        raise RateRejected("stale")

    monkeypatch.setattr(svc, "guarded_usd_rate", _reject)
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    assert _code(err.value) == "fx_unavailable"
    assert err.value.status_code == 502


async def test_an_overdue_pending_does_not_block_a_new_one(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    old = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    await _overdue(db_session, old)
    new = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    await db_session.refresh(old)
    assert old.status == "expired"
    assert new.amount_uzs == 20_001  # the expired one still holds 20 000 in quarantine


async def test_cancelling_an_overdue_one_is_refused_and_twice_is_a_no_op(
    db_session: AsyncSession,
) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    late = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    await _overdue(db_session, late)
    with pytest.raises(AppError) as err:
        await svc.cancel(db_session, merchant_id=m, number=late.number)
    assert _code(err.value) == "p2p_not_cancellable"
    assert late.status == "expired"

    r = await svc.reserve(db_session, merchant_id=m, amount_uzs=30_000, idempotency_key=None)
    once = await svc.cancel(db_session, merchant_id=m, number=r.number)
    twice = await svc.cancel(db_session, merchant_id=m, number=r.number)
    assert (once.status, twice.status) == ("cancelled", "cancelled")
    assert twice.closed_at == once.closed_at


async def test_a_lost_one_pending_race_is_a_conflict(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The twin committed between the guard and the insert: the index decides, 409."""
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    first = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="a")

    async def _missed(*_: object) -> None:
        return None

    monkeypatch.setattr(svc, "_guard_open", _missed)
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=30_000, idempotency_key="b")
    assert _code(err.value) == "p2p_reservation_open"
    assert err.value.extra.get("number") == first.number
