"""The worker: drain the Postgres-native fulfilment queue.

LISTEN fulfillment_queue for instant wake-ups; a lazy poll tick
(fulfilment_poll_seconds) catches notifications lost to restarts. The rows
in fulfillment_tasks are the queue — this process holds no state worth
preserving and can be killed at any moment: row locks die with the
connection and the next tick reclaims the work.

Run as: ``python -m yupay_worker.consumer``.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
from sqlalchemy.ext.asyncio import async_sessionmaker

# Importing the API's router package first -- before anything imports
# ``fulfillment.api`` -- is what makes the next import below work at all,
# and as a side effect resolves every module's ORM mappers (each router
# import pulls in its module's ``models.py``) before ``drain_pending_tasks``
# runs its first cross-table query. Same fix and same reasoning as
# ``test_fulfillment_async.py``'s ``import yupay.api.v1``: ``fulfillment.api``
# pulls in ``fulfillment.routes``, which imports ``yupay.api.v1.deps`` --
# importing ``fulfillment.api`` on its own before ``yupay.api.v1`` exists
# starts that chain from the wrong end and deadlocks on a partially
# initialised ``fulfillment.api`` module.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.config import get_settings
from yupay.core.db import get_engine
from yupay.core.logging import configure_logging, get_logger
from yupay.modules.fulfillment.api import drain_pending_tasks
from yupay.modules.fulfillment.suppliers.g2b_client import close_g2b_pool

configure_logging()
log = get_logger("yupay.worker.consumer")

CHANNEL = "fulfillment_queue"


def raw_dsn(url: str) -> str:
    """Strip SQLAlchemy's ``+asyncpg`` driver suffix for a bare asyncpg DSN."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _wait_for_wake_or_tick(
    wake: asyncio.Event, stop: asyncio.Event, *, seconds: float
) -> None:
    """Return on whichever comes first: a NOTIFY wake-up, a stop signal, or the poll tick.

    Consumes (clears) ``wake`` before returning so a notification that lands
    mid-tick doesn't immediately re-fire the next wait -- the caller is about
    to drain anyway, so the signal has done its job.
    """
    wake_wait = asyncio.create_task(wake.wait())
    stop_wait = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait(
            {wake_wait, stop_wait}, timeout=seconds, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (wake_wait, stop_wait):
            if not task.done():
                task.cancel()
        # Let cancellation actually land instead of leaving these to warn
        # "Task was destroyed but it is pending" at garbage-collection time.
        await asyncio.gather(wake_wait, stop_wait, return_exceptions=True)
    if wake.is_set():
        wake.clear()


class ListenerManager:
    """Owns the asyncpg LISTEN connection on ``fulfillment_queue`` and its
    reconnect story.

    LISTEN is a pure accelerant: it wakes the consumer loop the instant a
    task lands instead of waiting out the poll tick. It is never the queue's
    only path -- the poll tick is what makes a dropped connection self-heal
    without anyone paging, because ``ensure()`` is retried once per tick.
    Every failure inside ``ensure()`` is therefore swallowed and logged,
    never raised: a Postgres blip must degrade the worker to "polls every N
    seconds", not crash the process holding the actual queue drain.
    """

    def __init__(
        self,
        dsn: str,
        wake: asyncio.Event,
        *,
        connect: Callable[[str], Awaitable[asyncpg.Connection]] = asyncpg.connect,
    ) -> None:
        self._dsn = dsn
        self._wake = wake
        self._connect = connect
        self._conn: asyncpg.Connection | None = None

    @property
    def connected(self) -> bool:
        """Whether a live LISTEN connection is currently held."""
        return self._conn is not None and not self._conn.is_closed()

    async def ensure(self) -> None:
        """(Re)establish the LISTEN connection if it is missing or dead.

        Never raises -- see the class docstring. A caller that wants to know
        whether LISTEN is actually up reads :attr:`connected` afterwards.
        """
        if self.connected:
            return
        self._conn = None
        try:
            conn = await self._connect(self._dsn)
            await conn.add_listener(CHANNEL, self._on_notify)
        except Exception:  # degrade to polling, never crash the loop
            log.exception("worker.consumer.listen_failed")
            return
        self._conn = conn

    def _on_notify(
        self,
        connection: object,  # noqa: ARG002 -- asyncpg's fixed callback signature
        pid: int,  # noqa: ARG002
        channel: str,  # noqa: ARG002
        payload: object,  # noqa: ARG002
    ) -> None:
        """Wake the consumer loop.

        The notification carries no information the loop needs --
        ``fulfillment_tasks`` itself is re-queried on wake, so this is a pure
        signal, not a message.
        """
        self._wake.set()

    async def close(self) -> None:
        """Close the LISTEN connection, if any. Idempotent."""
        if self._conn is None:
            return
        conn, self._conn = self._conn, None
        await conn.close()


async def run() -> None:
    """Drain the fulfilment queue until told to stop.

    LISTEN gives instant wake-ups; the poll tick guarantees forward progress
    no matter what LISTEN is doing. Nothing here is stateful across
    iterations except the connections themselves -- kill the process at any
    point and the next start (or another replica) picks up exactly where the
    row locks left off.
    """
    cfg = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    wake = asyncio.Event()
    listener = ListenerManager(raw_dsn(cfg.database_url), wake)
    log.info("worker.consumer.started", poll_seconds=cfg.fulfilment_poll_seconds)
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    while not stop.is_set():
        await listener.ensure()  # (re)connect w/ backoff via the poll-tick cadence, LISTEN
        await _wait_for_wake_or_tick(wake, stop, seconds=cfg.fulfilment_poll_seconds)
        if stop.is_set():
            break
        async with session_factory() as db:
            try:
                # Drain until dry: one NOTIFY or tick may cover more pending
                # tasks than a single batch (limit=20), so keep claiming
                # until a batch comes back empty. Commit after every batch --
                # the invariant a crash must preserve is "loses nothing but
                # row locks", not "loses nothing".
                while await drain_pending_tasks(db) > 0:
                    await db.commit()
                await db.commit()
            except Exception:
                # Outer belt for infra failures (DB down, etc.). A poisoned
                # individual task is already contained inside
                # drain_pending_tasks's own per-task savepoint and never
                # escapes to reach here.
                log.exception("worker.consumer.drain_failed")
                await db.rollback()

    await listener.close()
    await close_g2b_pool()
    log.info("worker.consumer.stopped")


if __name__ == "__main__":
    asyncio.run(run())
