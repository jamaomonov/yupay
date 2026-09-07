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

import pytest
from yupay.core.config import get_settings
from yupay_worker import consumer
from yupay_worker.consumer import (
    ListenerManager,
    Queue,
    _await_stray_tasks,
    _drain_all,
    _queue_loop,
    _queues,
    _supervise,
    _wait_for_wake_or_tick,
    raw_dsn,
    run,
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
        "postgresql://x", [asyncio.Event()], channel="fulfillment_queue", connect=exploding_connect
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
        _drain_all(factory, _queue(fake_drain, concurrency=concurrency)), timeout=5
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

    await _drain_all(factory, _queue(fake_drain))

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

    await _drain_all(factory, _queue(fake_drain, concurrency=2))  # must not raise

    assert sum(s.rollbacks for s in factory.sessions) == 1
    assert sum(s.commits for s in factory.sessions) == 1


# ---------- two queues, one task each ----------


class _FakeConnection:
    """The two asyncpg methods ``ListenerManager`` calls, and nothing else."""

    def __init__(self) -> None:
        self.channels: list[str] = []
        self.callbacks: list[Any] = []
        self.closed = False

    async def add_listener(self, channel: str, callback: Any) -> None:
        self.channels.append(channel)
        self.callbacks.append(callback)

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


def _listener(*wakes: asyncio.Event) -> tuple[ListenerManager, _FakeConnection]:
    connection = _FakeConnection()

    async def _connect(dsn: str) -> Any:
        return connection

    return ListenerManager("postgresql://x", wakes, channel="c", connect=_connect), connection


async def test_a_notification_on_one_channel_wakes_every_queue() -> None:
    """A wake drains **both** queues -- an empty one answers 0 on its first
    claim and returns, which costs less than routing wake-ups by channel."""
    fulfilment, webhooks = asyncio.Event(), asyncio.Event()
    manager, connection = _listener(fulfilment, webhooks)
    await manager.ensure()

    connection.callbacks[0](None, 0, "c", None)

    assert fulfilment.is_set()
    assert webhooks.is_set()


async def test_each_queue_has_its_own_event_so_one_cannot_eat_the_others_wake() -> None:
    """The reason a *shared* event is wrong once each queue has its own loop:
    ``_wait_for_wake_or_tick`` consumes what it waited on, so the first loop to
    return would clear a flag the second has not read yet and that loop waits
    out a whole tick for a signal already thrown away."""
    fulfilment, webhooks = asyncio.Event(), asyncio.Event()
    manager, connection = _listener(fulfilment, webhooks)
    await manager.ensure()
    connection.callbacks[0](None, 0, "c", None)

    await _wait_for_wake_or_tick(fulfilment, asyncio.Event(), seconds=5)

    assert not fulfilment.is_set()  # consumed by the loop that read it
    assert webhooks.is_set()  # and the other queue's signal survives


async def test_a_slow_queue_does_not_pace_the_other() -> None:
    """The coupling this shape exists to remove, measured against its own control.

    With both queues drained inside one awaited ``gather``, the call returned
    with its slowest member, so a slow webhook drain became the fulfilment
    queue's polling period. The real scenario is a re-enabled hook with a large
    backlog against a slow-but-healthy endpoint: hours of draining, with every
    paid order waiting behind it.

    A bare "more than N drains" assertion would pass for reasons that have
    nothing to do with the fix, so this runs the **coupled** shape too, in the
    same window with the same fakes, and compares. That control is the whole
    test: it is what makes the number mean something.
    """
    window, slow_drain, tick = 0.6, 0.25, 0.01

    def _fakes() -> tuple[Any, Any, list[int]]:
        counter = [0]

        async def fast(db: Any) -> int:
            counter[0] += 1
            return 0

        async def slow(db: Any) -> int:
            await asyncio.sleep(slow_drain)
            return 0

        return fast, slow, counter

    async def _measure_decoupled() -> int:
        fast, slow, counter = _fakes()
        stop = asyncio.Event()
        wakes = (asyncio.Event(), asyncio.Event())
        factory = _FakeSessionFactory()
        loops = [
            asyncio.create_task(
                _queue_loop(
                    factory,
                    _queue(drain, name=name),
                    listener=_listener(*wakes)[0],
                    wake=wake,
                    stop=stop,
                    poll_seconds=tick,
                )
            )
            for drain, name, wake in ((fast, "fast", wakes[0]), (slow, "slow", wakes[1]))
        ]
        try:
            await asyncio.sleep(window)
            stop.set()
            await asyncio.wait_for(asyncio.gather(*loops), timeout=5)
        finally:
            for task in loops:
                task.cancel()
        return counter[0]

    async def _measure_coupled() -> int:
        """The shape this replaced: one loop, one gather across both queues."""
        fast, slow, counter = _fakes()
        stop = asyncio.Event()
        factory = _FakeSessionFactory()
        queues = (_queue(fast, name="fast"), _queue(slow, name="slow"))

        async def _both() -> None:
            while not stop.is_set():
                await _wait_for_wake_or_tick(asyncio.Event(), stop, seconds=tick)
                if stop.is_set():
                    break
                await asyncio.gather(*(_drain_all(factory, queue) for queue in queues))

        task = asyncio.create_task(_both())
        try:
            await asyncio.sleep(window)
            stop.set()
            await asyncio.wait_for(task, timeout=5)
        finally:
            task.cancel()
        return counter[0]

    decoupled = await _measure_decoupled()
    coupled = await _measure_coupled()

    assert coupled < window / slow_drain + 2, coupled  # paced by the slow queue
    assert decoupled > 10, decoupled
    assert decoupled > coupled * 3, (decoupled, coupled)


async def test_a_queue_loop_stops_on_the_shared_stop_event() -> None:
    stop = asyncio.Event()
    drains = 0

    async def drain(db: Any) -> int:
        nonlocal drains
        drains += 1
        return 0

    task = asyncio.create_task(
        _queue_loop(
            _FakeSessionFactory(),
            _queue(drain),
            listener=_listener(asyncio.Event())[0],
            wake=asyncio.Event(),
            stop=stop,
            poll_seconds=0.01,
        )
    )
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert drains > 0


async def test_an_empty_queue_costs_one_query_and_returns() -> None:
    """The cheap half of "a wake drains both": a queue with nothing due
    answers 0 on its first claim and the drainer stops."""
    calls = 0

    async def fake_drain(db: Any) -> int:
        nonlocal calls
        calls += 1
        return 0

    await _drain_all(_FakeSessionFactory(), _queue(fake_drain))

    assert calls == 1


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


# ---------- what run() actually builds, and what happens when a loop dies ----------


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Run ``run()`` for real, with only its I/O replaced.

    The listeners are the **real** ``ListenerManager``: nothing connects until
    ``ensure()``, which the fake loop never calls, and ``close()`` on an
    unopened one is a no-op. What is faked is the engine, the session factory,
    the G2B pool and ``_queue_loop`` itself — so what is under test is the
    wiring ``run()`` does, which is where the two properties below live.
    """
    started: list[dict[str, Any]] = []
    monkeypatch.setattr(consumer, "get_engine", lambda: None)
    monkeypatch.setattr(consumer, "async_sessionmaker", lambda *a, **k: _FakeSessionFactory())

    async def _noop_pool() -> None:
        return None

    monkeypatch.setattr(consumer, "close_g2b_pool", _noop_pool)
    return started


def _install_loop(
    monkeypatch: pytest.MonkeyPatch, started: list[dict[str, Any]], body: Any
) -> None:
    async def _fake_loop(
        session_factory: Any,
        queue: Queue,
        *,
        listener: Any,
        wake: asyncio.Event,
        stop: asyncio.Event,
        poll_seconds: float,
    ) -> None:
        started.append({"queue": queue, "listener": listener, "wake": wake, "stop": stop})
        await body(len(started), stop)

    monkeypatch.setattr(consumer, "_queue_loop", _fake_loop)


async def test_run_gives_every_queue_its_own_task_and_its_own_wake_event(
    monkeypatch: pytest.MonkeyPatch, wired: list[dict[str, Any]]
) -> None:
    """The properties the fix is made of, asserted where the fix lives.

    Both are invisible to a test that drives ``_queue_loop`` directly with its
    own events: a ``run()`` that re-shared one event
    (``wakes = (shared,) * len(queues)``) or re-coupled the loops would leave
    those green. This one reads what ``run()`` itself handed each queue.
    """

    async def _body(nth: int, stop: asyncio.Event) -> None:
        if nth == len(_queues(get_settings())):
            stop.set()  # both are up; shut down
        await stop.wait()

    _install_loop(monkeypatch, wired, _body)

    assert await asyncio.wait_for(run(), timeout=5) == 0

    assert [call["queue"].name for call in wired] == [q.name for q in _queues(get_settings())]
    # One task each is implied by two calls; the events and listeners must be
    # distinct objects, which is the half a shared-event regression would break.
    assert len({id(call["wake"]) for call in wired}) == len(wired)
    assert len({id(call["listener"]) for call in wired}) == len(wired)
    # ...and one stop, shared, or a signal would only stop one queue.
    assert len({id(call["stop"]) for call in wired}) == 1


async def test_run_exits_non_zero_when_a_queue_loop_dies(
    monkeypatch: pytest.MonkeyPatch, wired: list[dict[str, Any]]
) -> None:
    """A dead queue must take the container down.

    Unsupervised, the process stayed **up, healthy-looking and one queue
    short**: no log line, no non-zero exit, nothing for
    ``restart: unless-stopped`` to restart — only a GC-time "Task exception was
    never retrieved" on stderr. Decoupling the queues removed the crash that
    used to make a dead queue visible, and the consequence is the outage the
    decoupling was for.
    """

    async def _body(nth: int, stop: asyncio.Event) -> None:
        if nth == 1:
            raise RuntimeError("the listener blew up")
        await stop.wait()

    _install_loop(monkeypatch, wired, _body)

    assert await asyncio.wait_for(run(), timeout=5) == 1
    assert wired[-1]["stop"].is_set(), "the surviving loops must be wound down too"


async def test_shutdown_spends_one_budget_and_not_two(
    monkeypatch: pytest.MonkeyPatch, wired: list[dict[str, Any]]
) -> None:
    """A stuck drain must not be waited on twice.

    ``_await_stray_tasks`` collects ``asyncio.all_tasks()``, which now includes
    the queue loops, so before ``exclude=`` a loop that ignored its own bounded
    wait went on to spend the **stray** window too. That made the two
    five-second budgets one ten-second total — exactly Docker's default
    ``stop_grace_period``, which neither compose file overrides for ``worker``,
    so ``close_g2b_pool()`` and the ``stopped`` line were SIGKILLed away.

    Scaled down so the test costs a tenth of a second: with the fix the whole
    shutdown is the drain slice (0.1) and the strays return at once; without
    it, the strays wait out the rest of the budget as well (0.5).
    """
    monkeypatch.setattr(consumer, "SHUTDOWN_BUDGET_SECONDS", 0.5)
    monkeypatch.setattr(consumer, "SHUTDOWN_DRAIN_SECONDS", 0.1)

    async def _body(nth: int, stop: asyncio.Event) -> None:
        if nth == len(_queues(get_settings())):
            stop.set()
        await asyncio.sleep(30)  # ignores the stop signal: the stuck-drain shape

    _install_loop(monkeypatch, wired, _body)

    started = time.monotonic()
    try:
        assert await asyncio.wait_for(run(), timeout=5) == 0
        elapsed = time.monotonic() - started
        assert elapsed < 0.3, elapsed
    finally:
        stuck = [t for t in asyncio.all_tasks() if t.get_name().startswith("drain:")]
        for task in stuck:
            task.cancel()
        await asyncio.gather(*stuck, return_exceptions=True)


def test_the_shutdown_budget_stays_under_dockers_grace_period() -> None:
    """The number this is measured against lives outside the repo.

    Docker's default ``stop_grace_period`` is 10 s and neither compose file
    overrides it for ``worker``, so a shutdown budget at or past it is a
    shutdown that gets SIGKILLed part-way through. Raising this means setting
    ``stop_grace_period`` in both compose files first, which is why the
    constant is asserted here rather than trusted to a comment.
    """
    assert consumer.SHUTDOWN_BUDGET_SECONDS < 10
    assert consumer.SHUTDOWN_DRAIN_SECONDS < consumer.SHUTDOWN_BUDGET_SECONDS


async def test_supervise_returns_quietly_on_an_ordinary_stop() -> None:
    stop = asyncio.Event()

    async def _loop() -> None:
        await stop.wait()

    loops = [asyncio.create_task(_loop(), name="drain:x")]
    stop.set()
    assert await asyncio.wait_for(_supervise(loops, stop=stop), timeout=5) is False
    await asyncio.gather(*loops)


async def test_supervise_treats_a_loop_that_just_returns_as_a_dead_queue() -> None:
    """``_queue_loop`` has one exit and it is the stop signal, so a return
    without one is the same dead queue by a quieter route."""
    stop = asyncio.Event()

    async def _returns_early() -> None:
        return None

    loops = [asyncio.create_task(_returns_early(), name="drain:x")]
    assert await asyncio.wait_for(_supervise(loops, stop=stop), timeout=5) is True
    assert stop.is_set()


async def test_a_queue_that_crashes_does_not_stop_the_other_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-queue direction, at the loop level.

    A drain that raises is already contained (``_drain_until_dry`` catches and
    ``_drain_all`` gathers with ``return_exceptions=True``), so the way to kill
    a whole loop is its listener. The other queue must keep draining; ``run()``
    then turns the dead one into a non-zero exit, which is the test above.
    """
    stop = asyncio.Event()
    drains = 0

    async def healthy_drain(db: Any) -> int:
        nonlocal drains
        drains += 1
        return 0

    async def exploding_ensure() -> None:
        raise RuntimeError("listen connection is unusable")

    broken, _ = _listener(asyncio.Event())
    monkeypatch.setattr(broken, "ensure", exploding_ensure)

    dead = asyncio.create_task(
        _queue_loop(
            _FakeSessionFactory(),
            _queue(healthy_drain, name="dead"),
            listener=broken,
            wake=asyncio.Event(),
            stop=stop,
            poll_seconds=0.01,
        )
    )
    alive = asyncio.create_task(
        _queue_loop(
            _FakeSessionFactory(),
            _queue(healthy_drain, name="alive"),
            listener=_listener(asyncio.Event())[0],
            wake=asyncio.Event(),
            stop=stop,
            poll_seconds=0.01,
        )
    )
    try:
        await asyncio.sleep(0.15)
        assert dead.done()
        assert not alive.done()
        assert drains > 0, "the surviving queue kept draining"
    finally:
        stop.set()
        dead.cancel()
        alive.cancel()
        await asyncio.gather(dead, alive, return_exceptions=True)


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
