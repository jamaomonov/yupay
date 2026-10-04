"""Exact-amount reservations (spec §5.3, D1–D7)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.errors import AppError
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.models import P2PReservation

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    RATE,
    _card,
    _code,
    _fixed_rate,
    _merchant,
    _open,
)

pytestmark = pytest.mark.asyncio


async def test_reserves_the_exact_amount_and_freezes_the_rate(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])

    r = await svc.reserve(db_session, merchant_id=m, amount_uzs=50_000, idempotency_key="k1")

    assert r.amount_uzs == 50_000
    assert r.status == "pending"
    assert r.holds_amount
    assert r.fx_rate == RATE
    assert r.amount_usd == Decimal("4.06")  # 50000 / 12300 = 4.0650… → ROUND_DOWN
    assert r.expires_at - r.created_at == timedelta(minutes=5)
    assert r.number.startswith("T")


async def test_a_held_amount_bumps_the_next_one_by_a_som(db_session: AsyncSession) -> None:
    await _card(db_session)
    a, b = await _merchant(db_session), await _merchant(db_session)
    await _open(db_session, [a, b])

    first = await svc.reserve(db_session, merchant_id=a, amount_uzs=50_000, idempotency_key=None)
    second = await svc.reserve(db_session, merchant_id=b, amount_uzs=50_000, idempotency_key=None)

    assert (first.amount_uzs, second.amount_uzs) == (50_000, 50_001)


async def test_same_key_returns_the_same_reservation(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    one = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="k")
    two = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="k")
    assert one.id == two.id


async def test_one_pending_per_merchant(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=30_000, idempotency_key=None)
    assert _code(err.value) == "p2p_reservation_open"


async def test_bounds_and_switch(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    with pytest.raises(AppError) as off:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    assert _code(off.value) == "p2p_disabled"
    await _open(db_session, [m])
    for amount in (9_999, 10_000_001):
        with pytest.raises(AppError) as err:
            await svc.reserve(db_session, merchant_id=m, amount_uzs=amount, idempotency_key=None)
        assert _code(err.value) == "p2p_no_card"


async def test_cancel_quarantines_then_sweep_releases(db_session: AsyncSession) -> None:
    await _card(db_session)
    a, b = await _merchant(db_session), await _merchant(db_session)
    await _open(db_session, [a, b])
    r = await svc.reserve(db_session, merchant_id=a, amount_uzs=40_000, idempotency_key=None)

    cancelled = await svc.cancel(db_session, merchant_id=a, number=r.number)
    assert cancelled.status == "cancelled"
    assert cancelled.holds_amount
    assert cancelled.quarantine_until is not None

    # Quarantined: the next reservation of 40 000 gets 40 001.
    nxt = await svc.reserve(db_session, merchant_id=b, amount_uzs=40_000, idempotency_key=None)
    assert nxt.amount_uzs == 40_001

    swept = await svc.sweep(db_session, now_=now() + timedelta(minutes=11))
    assert swept.released >= 1
    await db_session.refresh(cancelled)
    assert cancelled.holds_amount is False


async def test_expiry_is_exactly_five_minutes(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await svc.reserve(db_session, merchant_id=m, amount_uzs=15_000, idempotency_key=None)

    still = await svc.sweep(db_session, now_=r.expires_at - timedelta(seconds=1))
    assert still.expired == 0
    gone = await svc.sweep(db_session, now_=r.expires_at + timedelta(seconds=1))
    assert gone.expired == 1
    await db_session.refresh(r)
    assert r.status == "expired"
    assert r.holds_amount
    assert r.closed_at is not None
    assert r.quarantine_until == r.closed_at + timedelta(minutes=10)


async def test_paid_or_expired_cannot_be_cancelled(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await svc.reserve(db_session, merchant_id=m, amount_uzs=15_000, idempotency_key=None)
    await svc.sweep(db_session, now_=r.expires_at + timedelta(seconds=1))
    with pytest.raises(AppError) as err:
        await svc.cancel(db_session, merchant_id=m, number=r.number)
    assert _code(err.value) == "p2p_not_cancellable"


async def test_daily_limit_skips_a_full_card(db_session: AsyncSession) -> None:
    await _card(db_session, daily_limit_uzs=10_000)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    assert _code(err.value) == "p2p_no_card"


async def test_two_resellers_at_the_same_instant_get_different_amounts(
    db_engine: AsyncEngine,
) -> None:
    """Review Focus 3: the partial unique index, not a read, decides."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        await _card(setup)
        a, b = await _merchant(setup), await _merchant(setup)
        await _open(setup, [a, b])
        await setup.commit()

    async def one(mid: str) -> int:
        async with factory() as db:
            r = await svc.reserve(db, merchant_id=mid, amount_uzs=70_000, idempotency_key=None)
            await db.commit()
            return r.amount_uzs

    got = await asyncio.gather(one(a), one(b))
    assert sorted(got) == [70_000, 70_001]


async def test_stale_read_never_overwrites_a_paid_row(db_engine: AsyncEngine) -> None:
    """A payment that committed between our load and our expiry must win."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        await _card(setup)
        m = await _merchant(setup)
        await _open(setup, [m])
        r = await svc.reserve(setup, merchant_id=m, amount_uzs=15_000, idempotency_key=None)
        await setup.commit()
        number = r.number

    async with factory() as a:
        stale = await svc._own(a, m, number, lock=False)  # loaded while pending
        async with factory() as b:
            await b.execute(
                update(P2PReservation)
                .where(P2PReservation.number == number)
                .values(status="paid", closed_at=now())
            )
            await b.commit()
        await svc._expire_stale(a, stale, stale.expires_at + timedelta(seconds=1))
        assert stale.status == "paid"
    async with factory() as c:
        row = await svc.read(c, merchant_id=m, number=number)
        assert row.status == "paid"


async def test_read_expires_a_stale_pending(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await svc.reserve(db_session, merchant_id=m, amount_uzs=15_000, idempotency_key=None)
    await db_session.execute(
        update(P2PReservation)
        .where(P2PReservation.id == r.id)
        .values(expires_at=now() - timedelta(seconds=1))
    )
    got = await svc.read(db_session, merchant_id=m, number=r.number)
    assert got.status == "expired"
    assert got.holds_amount


async def test_same_key_race_returns_one_reservation(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        await _card(setup)
        m = await _merchant(setup)
        await _open(setup, [m])
        await setup.commit()

    async def one() -> str:
        async with factory() as db:
            r = await svc.reserve(db, merchant_id=m, amount_uzs=30_000, idempotency_key="same")
            await db.commit()
            return r.number

    n1, n2 = await asyncio.gather(one(), one())
    assert n1 == n2
    async with factory() as check:
        count = await check.scalar(
            select(func.count()).select_from(P2PReservation).where(P2PReservation.merchant_id == m)
        )
    assert count == 1


async def test_card_max_amount_is_reservable_but_leaves_no_headroom(
    db_session: AsyncSession,
) -> None:
    await _card(db_session)
    a, b = await _merchant(db_session), await _merchant(db_session)
    await _open(db_session, [a, b])
    r = await svc.reserve(db_session, merchant_id=a, amount_uzs=10_000_000, idempotency_key=None)
    assert r.amount_uzs == 10_000_000
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=b, amount_uzs=10_000_000, idempotency_key=None)
    assert _code(err.value) == "p2p_amount_busy"


async def test_list_pages_with_a_cursor(db_session: AsyncSession) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    for i in range(3):
        r = await svc.reserve(
            db_session, merchant_id=m, amount_uzs=20_000 + i * 1000, idempotency_key=None
        )
        await svc.cancel(db_session, merchant_id=m, number=r.number)
    page1, cursor = await svc.list_for_merchant(db_session, merchant_id=m, limit=2, cursor=None)
    assert len(page1) == 2
    assert cursor is not None
    page2, cursor2 = await svc.list_for_merchant(db_session, merchant_id=m, limit=2, cursor=cursor)
    assert len(page2) == 1
    assert cursor2 is None
    assert {x.id for x in page1}.isdisjoint({x.id for x in page2})
    clamped, _ = await svc.list_for_merchant(db_session, merchant_id=m, limit=0, cursor=None)
    assert len(clamped) == 1
