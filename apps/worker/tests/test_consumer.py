"""Unit tests for the Postgres-queue consumer's pure seams.

Fakes only, no DB. The DB-touching paths (``drain_pending_tasks`` and
``drain_pending_deliveries`` themselves, claim/execute/commit under
concurrency) are proven end-to-end in
``apps/api/tests/integration/test_fulfillment_async.py`` and
``test_merchant_webhook_delivery.py`` -- this file owns only the consumer
loop's own logic: the wake/tick race, the listener's never-raise reconnect
contract, the fan-out to K independent drainers **per queue**, and the
shutdown window for fire-and-forget notification sends.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from yupay.core.config import get_settings
from yupay_worker.consumer import (
    ListenerManager,
    Queue,
    _await_stray_tasks,
    _drain_all,
    _queues,
    _wait_for_wake_or_tick,
    raw_dsn,
)


def _queue(drain: Any, *, name: str = "test", concurrency: int = 1) -> Queue:
    """A queue whose drain is a fake -- the loop's own logic is what is under
    test here, never the SQL."""
    return Queue(name=name, channel=f"{name}_queue", drain=drain, concurrency=concurrency)


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

    mgr = ListenerManager(
        "postgresql://x", asyncio.Event(), channel="fulfillment_queue", connect=exploding_connect
    )
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


async def test_drainers_run_in_parallel_each_on_its_own_session() -> None:
    """K drainers must be genuinely concurrent and must not share a session.

    The fake drain blocks until all K have entered it, so a sequential
    implementation cannot finish this test at all -- the ``wait_for`` is the
    assertion. Separate sessions matter because ``AsyncSession`` is not safe
    under concurrent use.
    """
    concurrency = 4
    all_in = asyncio.Event()
    entered = 0

    async def fake_drain(db: Any) -> int:
        nonlocal entered
        entered += 1
        if entered == concurrency:
            all_in.set()
        await all_in.wait()
        return 0

    factory = _FakeSessionFactory()

    await asyncio.wait_for(
        _drain_all(factory, (_queue(fake_drain, concurrency=concurrency),)), timeout=5
    )

    assert len(factory.sessions) == concurrency
    assert len({id(s) for s in factory.sessions}) == concurrency  # no sharing
    assert all(s.commits == 1 for s in factory.sessions)  # each commits its own work
    assert all(s.closed for s in factory.sessions)


async def test_drainer_commits_after_every_batch() -> None:
    """Drain-until-dry: a full batch is committed before the next is claimed,
    so a crash mid-drain loses only the batch in flight."""
    batches = [20, 20, 0]

    async def fake_drain(db: Any) -> int:
        return batches.pop(0)

    factory = _FakeSessionFactory()

    await _drain_all(factory, (_queue(fake_drain),))

    assert factory.sessions[0].commits == 3  # two full batches + the dry one


async def test_one_drainers_failure_neither_escapes_nor_stops_the_others() -> None:
    """An infra failure (DB down, a deadlock with a refund cascade) must roll
    that drainer back and leave the rest of the fan-out working -- ``gather``
    must never see the exception."""
    calls = 0

    async def fake_drain(db: Any) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("connection reset")
        return 0

    factory = _FakeSessionFactory()

    await _drain_all(factory, (_queue(fake_drain, concurrency=2),))  # must not raise

    assert sum(s.rollbacks for s in factory.sessions) == 1
    assert sum(s.commits for s in factory.sessions) == 1


# ---------- two queues, one loop ----------


async def test_one_wake_drains_every_queue() -> None:
    """The merchant-webhook outbox is a second queue on the same loop. A wake
    (or a tick) has to drain both, or one NOTIFY would leave the other queue
    waiting on the next tick for no reason."""
    drained: list[str] = []

    def _recorder(name: str) -> Any:
        async def _drain(db: Any) -> int:
            drained.append(name)
            return 0

        return _drain

    await _drain_all(
        _FakeSessionFactory(),
        (_queue(_recorder("tasks"), name="tasks"), _queue(_recorder("hooks"), name="hooks")),
    )

    assert sorted(drained) == ["hooks", "tasks"]


async def test_an_empty_queue_costs_one_query_and_returns() -> None:
    """The cheap half of "a wake drains both": a queue with nothing due
    answers 0 on its first claim and the drainer stops."""
    calls = 0

    async def fake_drain(db: Any) -> int:
        nonlocal calls
        calls += 1
        return 0

    await _drain_all(_FakeSessionFactory(), (_queue(fake_drain),))

    assert calls == 1


async def test_a_queue_that_crashes_does_not_stop_the_other_queue() -> None:
    """The webhook drain reaches a third party's server; the fulfilment drain
    must not be taken down with it, in either direction."""
    ran = 0

    async def exploding(db: Any) -> int:
        raise OSError("connection reset")

    async def healthy(db: Any) -> int:
        nonlocal ran
        ran += 1
        return 0

    await _drain_all(
        _FakeSessionFactory(),
        (_queue(exploding, name="bad"), _queue(healthy, name="good")),
    )

    assert ran == 1


def test_the_two_queues_are_the_two_channels_their_producers_notify() -> None:
    """A channel spelled twice is a queue nobody drains and no test fails, so
    both names come from the modules that emit them."""
    from yupay.modules.merchants.api import WEBHOOK_QUEUE_CHANNEL

    channels = [queue.channel for queue in _queues(get_settings())]
    assert channels == ["fulfillment_queue", WEBHOOK_QUEUE_CHANNEL]


def test_each_queue_gets_its_own_concurrency_dial() -> None:
    """One dial for both would mean tuning a hung supplier call and a hung
    merchant endpoint with the same number."""
    cfg = get_settings()
    tasks, hooks = _queues(cfg)
    assert tasks.concurrency == cfg.fulfilment_concurrency
    assert hooks.concurrency == cfg.merchant_webhook_concurrency


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
