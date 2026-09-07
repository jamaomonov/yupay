"""Unit tests for how the worker process stops.

Fakes only, no DB. These moved here with ``yupay_worker.shutdown`` when
``consumer.py`` passed AGENTS §6's 500-line limit; the two tests that drive
``run()`` itself stayed in ``test_consumer.py``, because what they pin is the
*wiring* rather than this module — including the one that measures the budget
end to end against a stuck drain.
"""

from __future__ import annotations

import asyncio
import time

from yupay_worker import shutdown
from yupay_worker.shutdown import await_stray_tasks, supervise


def test_the_shutdown_budget_stays_under_dockers_grace_period() -> None:
    """The number this is measured against lives outside the repo.

    Docker's default ``stop_grace_period`` is 10 s and neither compose file
    overrides it for ``worker``, so a shutdown budget at or past it is a
    shutdown that gets SIGKILLed part-way through. Raising this means setting
    ``stop_grace_period`` in both compose files first, which is why the
    constant is asserted here rather than trusted to a comment.
    """
    assert shutdown.SHUTDOWN_BUDGET_SECONDS < 10
    assert shutdown.SHUTDOWN_DRAIN_SECONDS < shutdown.SHUTDOWN_BUDGET_SECONDS


async def test_supervise_returns_quietly_on_an_ordinary_stop() -> None:
    stop = asyncio.Event()

    async def _loop() -> None:
        await stop.wait()

    loops = [asyncio.create_task(_loop(), name="drain:x")]
    stop.set()
    assert await asyncio.wait_for(supervise(loops, stop=stop), timeout=5) is False
    await asyncio.gather(*loops)


async def test_supervise_treats_a_loop_that_just_returns_as_a_dead_queue() -> None:
    """``_queue_loop`` has one exit and it is the stop signal, so a return
    without one is the same dead queue by a quieter route."""
    stop = asyncio.Event()

    async def _returns_early() -> None:
        return None

    loops = [asyncio.create_task(_returns_early(), name="drain:x")]
    assert await asyncio.wait_for(supervise(loops, stop=stop), timeout=5) is True
    assert stop.is_set()


# ---------- the window for fire-and-forget sends ----------


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

    await await_stray_tasks(timeout=2.0)

    assert delivered
    assert not task.cancelled()


async def test_shutdown_wait_is_bounded_and_never_waits_on_itself() -> None:
    """A send that hangs must cost the shutdown its timeout, not forever --
    and the waiter must exclude its own task or it would wait on itself."""
    hanging = asyncio.create_task(asyncio.sleep(30))
    started = time.monotonic()
    try:
        await await_stray_tasks(timeout=0.2)
        assert time.monotonic() - started < 2
        assert not hanging.done()  # bounded wait, not a cancel
    finally:
        hanging.cancel()
