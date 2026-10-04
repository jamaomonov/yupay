"""Integration tests for the P2P sweep scheduler job (always the real ``run_p2p_sweep``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.redis import get_redis
from yupay.modules.p2p import reservations as svc
from yupay.modules.p2p.models import P2PIncoming, P2PReservation
from yupay_scheduler.jobs import p2p_sweep

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    _card,
    _fixed_rate,
    _merchant,
    _open,
)

pytestmark = pytest.mark.asyncio

_KEY = "p2p:silence-alert"


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """Point the job's own ``get_session_factory()`` at the test database.

    The test_g2b_reconcile.py pattern: no reset of the core.db singleton.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(p2p_sweep, "get_session_factory", lambda: factory)


@pytest_asyncio.fixture(autouse=True)
async def _clean_alert_key() -> AsyncIterator[None]:
    """Drop the de-dup key before and after each test so a failure cannot leak it."""
    redis = get_redis()
    await redis.delete(_KEY)
    try:
        yield
    finally:
        await redis.delete(_KEY)


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the ``kind`` of every admin alert the job sends."""
    kinds: list[str] = []

    async def fake(message: str, *, kind: str, **_: object) -> bool:
        kinds.append(kind)
        return True

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", fake)
    return kinds


async def _expired_reservation(db: AsyncSession) -> None:
    """Commit a reservation that the cabinet read() path has just expired."""
    await _card(db)
    m = await _merchant(db)
    await _open(db, [m])
    r = await svc.reserve(db, merchant_id=m, amount_uzs=50_000, idempotency_key="k1")
    await db.commit()
    t0 = now()
    await db.execute(
        update(P2PReservation)
        .where(P2PReservation.id == r.id)
        .values(created_at=t0 - timedelta(minutes=6), expires_at=t0 - timedelta(seconds=30))
    )
    await db.commit()
    await svc.read(db, merchant_id=m, number=r.number)
    await db.commit()


async def test_alerts_on_recent_expiry_with_no_incoming(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """Cabinet-path expiry and a HUMO feed that never spoke -> one silence alert."""
    await _expired_reservation(db_session)
    await p2p_sweep.run_p2p_sweep()
    assert alerts == ["p2p_silence"]


async def test_alert_is_deduplicated_across_runs(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """Two real ticks inside the hour -> the Redis NX guard keeps it to one alert."""
    await _expired_reservation(db_session)
    await p2p_sweep.run_p2p_sweep()
    await p2p_sweep.run_p2p_sweep()
    assert alerts == ["p2p_silence"]


async def test_no_alert_when_incoming_is_recent(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """A notification an hour ago means the feed is alive -> no alert."""
    await _expired_reservation(db_session)
    db_session.add(
        P2PIncoming(
            id=new_id(),
            business_connection_id="bc-1",
            telegram_message_id=1,
            kind="credit",
            raw_text="x",
            result="unmatched",
            received_at=now() - timedelta(hours=1),
        )
    )
    await db_session.commit()
    await p2p_sweep.run_p2p_sweep()
    assert alerts == []


async def test_a_failed_alert_is_retried_on_the_next_tick(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """send_admin_alert returning False must not burn the hour's de-dup key."""
    outcomes = iter([False, True])
    kinds: list[str] = []

    async def flaky(message: str, *, kind: str, **_: object) -> bool:
        kinds.append(kind)
        return next(outcomes)

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", flaky)
    await _expired_reservation(db_session)
    await p2p_sweep.run_p2p_sweep()
    assert await get_redis().get(_KEY) is None
    await p2p_sweep.run_p2p_sweep()
    assert kinds == ["p2p_silence", "p2p_silence"]
    assert await get_redis().get(_KEY) is not None


async def test_an_alert_that_raises_frees_the_key_and_is_logged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(message: str, *, kind: str, **_: object) -> bool:
        raise RuntimeError("telegram down")

    failed: list[dict[str, object]] = []

    def _error(event: str, **fields: object) -> None:
        failed.append({"event": event, **fields})

    monkeypatch.setattr(p2p_sweep, "send_admin_alert", boom)
    monkeypatch.setattr(p2p_sweep.log, "error", _error)
    await _expired_reservation(db_session)
    await p2p_sweep.run_p2p_sweep()  # swallowed: the next tick retries
    assert await get_redis().get(_KEY) is None
    assert failed == [{"event": "p2p_sweep.failed", "error": "RuntimeError"}]


async def test_a_failed_tick_logs_the_class_only_and_swallows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Log:
        def error(self, event: str, **fields: object) -> None:
            calls.append((event, fields))

        info = error

    class _BoomError(Exception):
        pass

    async def broken(*_: object, **__: object) -> None:
        raise _BoomError("row data that must not reach the log")

    monkeypatch.setattr(p2p_sweep, "log", _Log())
    monkeypatch.setattr(p2p_sweep, "sweep", broken)
    await p2p_sweep.run_p2p_sweep()
    assert calls == [("p2p_sweep.failed", {"error": "_BoomError"})]
