"""Unit tests for the Postgres-queue consumer's pure seams.

Fakes only, no DB. The heavy DB-touching path (``drain_pending_tasks`` itself,
claim/execute/commit under concurrency) is already proven end-to-end in
``apps/api/tests/integration/test_fulfillment_async.py`` -- this file owns
only the consumer loop's own logic: the wake/tick race and the listener's
never-raise reconnect contract.
"""

from __future__ import annotations

import asyncio
import time

from yupay_worker.consumer import ListenerManager, _wait_for_wake_or_tick, raw_dsn


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
