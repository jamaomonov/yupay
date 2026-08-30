"""Unit tests for the Postgres-queue consumer's pure seams.

Fakes only, no DB. The DB-touching path (``drain_pending_tasks`` itself,
claim/execute/commit under concurrency) is proven end-to-end in
``apps/api/tests/integration/test_fulfillment_async.py`` -- this file owns
only the consumer loop's own logic: the wake/tick race, the listener's
never-raise reconnect contract, the fan-out to K independent drainers, and
the shutdown window for fire-and-forget notification sends.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from yupay_worker import consumer
from yupay_worker.consumer import (
    ListenerManager,
    _await_stray_tasks,
    _drain_all,
    _wait_for_wake_or_tick,
    raw_dsn,
)


def test_raw_dsn_strips_the_driver() -> None:
    assert raw_dsn("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


async def test_wait_wakes_on_notification_before_the_tick() -> None:
    """A set wake-event must cut the wait short of the tick."""
    wake = asyncio.Event()
    wake.set()
    started = time.monotonic()
    await _wait_for_wake_or_tick(wake, asyncio.Event(), seconds=5)
    assert time.monotonic() - started < 0.5
    assert not wake.is_set()  # the wait consumes the wake


async def test_wait_times_out_into_a_tick() -> None:
    started = time.monotonic()
    await _wait_for_wake_or_tick(asyncio.Event(), asyncio.Event(), seconds=0.2)
    assert time.monotonic() - started >= 0.2


async def test_listener_failure_falls_back_to_polling() -> None:
    """If LISTEN cannot be (re)established, ensure() must swallow the error
    (logging it) and return -- the loop then lives on the poll tick alone.
    The connect dependency is injectable for exactly this test.
    """

    async def exploding_connect(dsn: str):
        raise OSError("no route to host")

    mgr = ListenerManager("postgresql://x", asyncio.Event(), connect=exploding_connect)
    await mgr.ensure()  # must not raise
    assert mgr.connected is False


# ---------- K parallel drainers ----------


class _FakeSession:
    """Stand-in for ``AsyncSession``: an async context manager that counts."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        self.closed = True
        return False

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeSessionFactory:
    """Records every session handed out, so a test can prove they differ."""

    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session


async def test_drainers_run_in_parallel_each_on_its_own_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K drainers must be genuinely concurrent and must not share a session.

    The fake drain blocks until all K have entered it, so a sequential
    implementation cannot finish this test at all -- the ``wait_for`` is the
    assertion. Separate sessions matter because ``AsyncSession`` is not safe
    under concurrent use.
    """
    concurrency = 4
    all_in = asyncio.Event()
    entered = 0

    async def fake_drain(db: Any, *, limit: int = 20) -> int:
        nonlocal entered
        entered += 1
        if entered == concurrency:
            all_in.set()
        await all_in.wait()
        return 0

    monkeypatch.setattr(consumer, "drain_pending_tasks", fake_drain)
    factory = _FakeSessionFactory()

    await asyncio.wait_for(_drain_all(factory, concurrency=concurrency), timeout=5)

    assert len(factory.sessions) == concurrency
    assert len({id(s) for s in factory.sessions}) == concurrency  # no sharing
    assert all(s.commits == 1 for s in factory.sessions)  # each commits its own work
    assert all(s.closed for s in factory.sessions)


async def test_drainer_commits_after_every_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drain-until-dry: a full batch is committed before the next is claimed,
    so a crash mid-drain loses only the batch in flight."""
    batches = [20, 20, 0]

    async def fake_drain(db: Any, *, limit: int = 20) -> int:
        return batches.pop(0)

    monkeypatch.setattr(consumer, "drain_pending_tasks", fake_drain)
    factory = _FakeSessionFactory()

    await _drain_all(factory, concurrency=1)

    assert factory.sessions[0].commits == 3  # two full batches + the dry one


async def test_one_drainers_failure_neither_escapes_nor_stops_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An infra failure (DB down, a deadlock with a refund cascade) must roll
    that drainer back and leave the rest of the fan-out working -- ``gather``
    must never see the exception."""
    calls = 0

    async def fake_drain(db: Any, *, limit: int = 20) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("connection reset")
        return 0

    monkeypatch.setattr(consumer, "drain_pending_tasks", fake_drain)
    factory = _FakeSessionFactory()

    await _drain_all(factory, concurrency=2)  # must not raise

    assert sum(s.rollbacks for s in factory.sessions) == 1
    assert sum(s.commits for s in factory.sessions) == 1


# ---------- shutdown window for fire-and-forget sends ----------


async def test_shutdown_waits_for_stray_tasks_without_cancelling_them() -> None:
    """``notifications.schedule`` sends run as bare ``create_task``s. The last
    batch's "your order is delivered" ping is still in flight when the loop
    exits, and ``asyncio.run`` would cancel it on the way out."""
    delivered = False

    async def stray_notification() -> None:
        nonlocal delivered
        await asyncio.sleep(0.05)
        delivered = True

    task = asyncio.create_task(stray_notification())

    await _await_stray_tasks(timeout=2.0)

    assert delivered
    assert not task.cancelled()


async def test_shutdown_wait_is_bounded_and_never_waits_on_itself() -> None:
    """A send that hangs must cost the shutdown its timeout, not forever --
    and the waiter must exclude its own task or it would wait on itself."""
    hanging = asyncio.create_task(asyncio.sleep(30))
    started = time.monotonic()
    try:
        await _await_stray_tasks(timeout=0.2)
        assert time.monotonic() - started < 2
        assert not hanging.done()  # bounded wait, not a cancel
    finally:
        hanging.cancel()
