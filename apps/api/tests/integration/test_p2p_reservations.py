"""Exact-amount reservations (spec §5.3, D1–D7)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.errors import AppError
from yupay.core.ids import new_id
from yupay.modules.merchants import service as merchants_service
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.cards import seal_pan
from yupay.modules.p2p.models import P2PCard
from yupay.modules.p2p.settings import load_settings

pytestmark = pytest.mark.asyncio
RATE = Decimal("12300")


@pytest.fixture(autouse=True)
def _fixed_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _rate(db: AsyncSession, *, quote: str, override_cache: object = None) -> Decimal:
        return RATE

    monkeypatch.setattr(svc, "guarded_usd_rate", _rate)


def _code(exc: AppError) -> object:
    """``AppError`` keeps ``code=`` in ``extra`` (core.errors), not as an attribute."""
    return exc.extra.get("code")


async def _card(db: AsyncSession, **over: object) -> P2PCard:
    ct, nonce = seal_pan("9860350146023311")
    card = P2PCard(
        id=new_id(),
        label="Humo main",
        pan_ciphertext=ct,
        pan_nonce=nonce,
        pan_last4="3311",
        holder_name="OMONOV J",
        network="humo",
        **over,
    )
    db.add(card)
    await db.flush()
    return card


async def _merchant(db: AsyncSession) -> str:
    """A merchant with its deposit account, the way test_merchant_deposit.py makes one."""
    merchant = await merchants_service.create_merchant(db, title=f"Reseller {new_id()[-6:]}")
    return merchant.id


async def _open(db: AsyncSession, merchant_ids: list[str]) -> None:
    s = await load_settings(db)
    s.mode = "allowlist"
    s.allowlist_merchant_ids = merchant_ids
    await db.flush()


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
