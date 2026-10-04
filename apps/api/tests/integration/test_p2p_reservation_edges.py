"""Reservation edge paths: rate gate, stale holds, overdue cancel, lost races, key replays."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.errors import AppError
from yupay.modules.p2p import card_choice
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.card_choice import eligible_cards
from yupay.modules.p2p.models import P2PCard, P2PReservation
from yupay.modules.pricing.fx_guard import RateRejected

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    RATE,
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


async def _no_prior(*_: object) -> None:
    """Stand-in for the first key lookup, as if the twin committed just after it."""


async def test_a_mismatch_seen_by_the_open_guard_is_a_conflict(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="k")

    monkeypatch.setattr(svc, "_prior", _no_prior)
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=30_000, idempotency_key="k")
    assert _code(err.value) == "p2p_idempotency_mismatch"


async def test_a_mismatch_seen_after_a_lost_race_is_a_conflict(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both lookups missed the twin: the index collision resolves to the same 409."""
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="k")

    real_prior = svc._prior
    calls = 0

    async def _first_lookup_misses(
        db: AsyncSession, merchant_id: str, key: str
    ) -> P2PReservation | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real_prior(db, merchant_id, key)

    async def _missed(*_: object) -> None:
        return None

    monkeypatch.setattr(svc, "_prior", _first_lookup_misses)
    monkeypatch.setattr(svc, "_guard_open", _missed)
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=30_000, idempotency_key="k")
    assert _code(err.value) == "p2p_idempotency_mismatch"
    assert calls == 2  # the second lookup is _after_race's


@pytest.mark.parametrize("requested", [20_050, 20_001, 19_900])
async def test_a_replay_for_more_or_far_less_than_stored_is_a_mismatch(
    db_session: AsyncSession, requested: int
) -> None:
    """A bump only goes up, by at most 99: no other request can have produced 20 000."""
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="k")
    with pytest.raises(AppError) as err:
        await svc.reserve(db_session, merchant_id=m, amount_uzs=requested, idempotency_key="k")
    assert _code(err.value) == "p2p_idempotency_mismatch"


@pytest.mark.parametrize("requested", [19_950, 19_901])
async def test_a_replay_for_slightly_less_than_stored_is_the_same_intent(
    db_session: AsyncSession, requested: int
) -> None:
    """19 950 could have been bumped to 20 000, so the stored row answers it (as ruled)."""
    await _card(db_session)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    first = await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key="k")
    again = await svc.reserve(db_session, merchant_id=m, amount_uzs=requested, idempotency_key="k")
    assert again.id == first.id


async def test_concurrent_holds_cannot_together_pass_the_daily_limit(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two 20 000 holds racing on a 30 000 limit: one card lock, one winner.

    Both requests are held at a rendezvous right after choosing a card, so without
    the lock both read an empty day. With it the second blocks on the lock instead,
    the first gives up waiting after a second and commits, and the second then
    reads 20 000 already held.
    """
    rendezvous = asyncio.Barrier(2)

    async def _meet_after_choosing(
        db: AsyncSession, amount: int, now_: datetime
    ) -> list[tuple[P2PCard, int]]:
        cards = await eligible_cards(db, amount, now_)
        with contextlib.suppress(TimeoutError, asyncio.BrokenBarrierError):
            await asyncio.wait_for(rendezvous.wait(), timeout=1.0)
        return cards

    monkeypatch.setattr(svc, "eligible_cards", _meet_after_choosing)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        await _card(setup, daily_limit_uzs=30_000)
        a, b = await _merchant(setup), await _merchant(setup)
        await _open(setup, [a, b])
        await setup.commit()

    async def one(mid: str) -> object:
        async with factory() as db:
            try:
                r = await svc.reserve(db, merchant_id=mid, amount_uzs=20_000, idempotency_key=None)
            except AppError as exc:
                return _code(exc)
            await db.commit()
            return r.amount_uzs

    got = await asyncio.gather(one(a), one(b))
    assert sorted(got, key=str) == [20_000, "p2p_no_card"]


async def test_the_rate_is_fetched_before_any_card_is_locked(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FX call may go to a provider: it must not run inside the card-lock window."""
    await _card(db_session, daily_limit_uzs=100_000)
    m = await _merchant(db_session)
    await _open(db_session, [m])
    events: list[str] = []
    real_lock = card_choice._lock_limited

    async def _lock(db: AsyncSession, cards: Sequence[P2PCard]) -> None:
        events.append("lock")
        await real_lock(db, cards)

    async def _rate(db: AsyncSession, *, quote: str, override_cache: object = None) -> Decimal:
        events.append("rate")
        return RATE

    monkeypatch.setattr(card_choice, "_lock_limited", _lock)
    monkeypatch.setattr(svc, "guarded_usd_rate", _rate)
    await svc.reserve(db_session, merchant_id=m, amount_uzs=20_000, idempotency_key=None)
    assert events == ["rate", "lock"]
