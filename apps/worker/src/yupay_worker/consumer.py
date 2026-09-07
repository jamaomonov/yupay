"""The worker: drain the Postgres-native queues.

Two of them now, and the second is why almost everything here is
parameterised by a :class:`Queue` rather than hardcoded:

- ``fulfillment_tasks`` / ``fulfillment_queue`` — the fulfilment work every
  retail order flows through (ADR-0064).
- ``merchant_webhook_deliveries`` / ``merchant_webhook_queue`` — the outgoing
  merchant webhooks (M3a). Its drain reaches a **third party's** server, which
  is the reason it has its own concurrency dial and its own LISTEN connection
  rather than sharing the fulfilment one: a hung supplier call and a hung
  merchant endpoint are different failures and should be tuned apart.

Each queue runs in its **own task**, on its own loop, so a slow queue delays
only itself. That is not tidiness: ``asyncio.gather`` returns with its slowest
member, so draining both queues in one awaited call made the webhook drain's
duration the fulfilment queue's polling period — a re-enabled hook with a large
backlog against a slow-but-healthy endpoint would have stalled every paid
order behind it for as long as that took.

LISTEN gives instant wake-ups; a lazy poll tick (``fulfilment_poll_seconds``)
catches notifications lost to restarts. A notification on **either** channel
wakes **every** queue — an empty queue costs one indexed query and returns,
which is far cheaper than routing wake-ups by channel and getting the routing
wrong. Each queue nonetheless owns its own ``asyncio.Event``: one shared event
between two consumers is a lost wake-up, because the first to return clears the
flag the second has not read yet.

The rows in those tables are the queues — this process holds no state worth
preserving and can be killed at any moment: row locks die with the connection
and the next tick reclaims the work.

Run as: ``python -m yupay_worker.consumer``.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from yupay.core.config import Settings, get_settings
from yupay.core.db import get_engine
from yupay.core.logging import configure_logging, get_logger
from yupay.modules.fulfillment.api import drain_pending_tasks
from yupay.modules.fulfillment.suppliers.g2b_client import close_g2b_pool
from yupay.modules.merchants.api import WEBHOOK_QUEUE_CHANNEL, drain_pending_deliveries

configure_logging()
log = get_logger("yupay.worker.consumer")

CHANNEL = "fulfillment_queue"

#: How long shutdown waits for a queue loop that is mid-drain before letting
#: the runtime cancel it. A cancelled drain rolls back its uncommitted batch,
#: so the cost is re-doing that batch, never losing it.
SHUTDOWN_DRAIN_SECONDS: Final = 5.0

#: One drain of one queue. Both drains take ``(db, *, limit=...)`` and return
#: how many rows the batch claimed; the loop only needs "did that do
#: anything", so the limit stays each module's own decision.
Drain = Callable[[AsyncSession], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class Queue:
    """One Postgres-native queue this process drains.

    Attributes:
        name: Short label for log lines. Not the table and not the channel.
        channel: The LISTEN channel its producer NOTIFYs on. Imported from
            the producing module, never respelled here — a channel spelled
            twice is a queue nobody drains and no test fails.
        drain: The module's claim-and-run function, behind its ``api`` facade.
        concurrency: Independent drainers to fan out per wake.
    """

    name: str
    channel: str
    drain: Drain
    concurrency: int


def _queues(cfg: Settings) -> tuple[Queue, ...]:
    """The queues this process drains, in the order a wake drains them.

    Fulfilment first: it is the money path, and a webhook is a courtesy.
    """
    return (
        Queue(
            name="fulfillment",
            channel=CHANNEL,
            drain=drain_pending_tasks,
            concurrency=cfg.fulfilment_concurrency,
        ),
        Queue(
            name="merchant_webhook",
            channel=WEBHOOK_QUEUE_CHANNEL,
            drain=drain_pending_deliveries,
            concurrency=cfg.merchant_webhook_concurrency,
        ),
    )


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
    """Owns one asyncpg LISTEN connection, on one channel, and its reconnect
    story.

    One instance per :class:`Queue`, parameterised rather than duplicated: two
    copies of this class would be two copies of the never-raise contract
    below, and the second copy is where it stops being true.

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
        wakes: Sequence[asyncio.Event],
        *,
        channel: str,
        connect: Callable[[str], Awaitable[asyncpg.Connection]] = asyncpg.connect,
    ) -> None:
        self._dsn = dsn
        self._wakes = tuple(wakes)
        self._channel = channel
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
            await conn.add_listener(self._channel, self._on_notify)
        except Exception:  # degrade to polling, never crash the loop
            log.exception("worker.consumer.listen_failed", channel=self._channel)
            return
        self._conn = conn

    def _on_notify(
        self,
        connection: object,  # noqa: ARG002 -- asyncpg's fixed callback signature
        pid: int,  # noqa: ARG002
        channel: str,  # noqa: ARG002
        payload: object,  # noqa: ARG002
    ) -> None:
        """Wake every queue's loop.

        The notification carries no information the loop needs -- each queue's
        table is re-queried on wake, so this is a pure signal, not a message.
        Every listener sets **every** queue's event, which is why one NOTIFY
        drains both queues: an empty one answers 0 on its first claim and
        returns, which costs less than routing wake-ups by channel.

        One event *per queue* rather than one shared between them, because
        ``_wait_for_wake_or_tick`` consumes what it waited on: with a single
        event the first loop to return clears the flag, and a second loop that
        was still draining when the NOTIFY landed waits out its whole tick for
        a signal that has already been thrown away.
        """
        for wake in self._wakes:
            wake.set()

    async def close(self) -> None:
        """Close the LISTEN connection, if any. Idempotent."""
        if self._conn is None:
            return
        conn, self._conn = self._conn, None
        await conn.close()


async def _drain_until_dry(session_factory: async_sessionmaker[AsyncSession], queue: Queue) -> None:
    """One drainer: claim-run-commit batches on its own session until dry.

    A session per drainer is mandatory, not tidiness: ``AsyncSession`` is not
    safe under concurrent use, so drainers sharing one would interleave
    statements on a single connection.

    Drain until dry: one NOTIFY or tick may cover more pending rows than a
    single batch (limit=20), so keep claiming until a batch comes back empty.
    Commit after every batch -- the invariant a crash must preserve is "loses
    nothing but row locks", not "loses nothing".
    """
    async with session_factory() as db:
        try:
            while await queue.drain(db) > 0:
                await db.commit()
            await db.commit()
        except Exception:
            # Outer belt for infra failures (DB down, a deadlock with a
            # concurrent refund cascade, etc.). A poisoned individual row is
            # already contained inside each drain's own per-row savepoint and
            # never escapes to reach here. Rolling back loses only this
            # drainer's uncommitted batch: its rows go back to ``pending`` and
            # the next tick reclaims them.
            log.exception("worker.consumer.drain_failed", queue=queue.name)
            await db.rollback()


async def _drain_all(session_factory: async_sessionmaker[AsyncSession], queue: Queue) -> None:
    """Run one queue's drainers, all of them, to completion.

    One queue, because the caller is that queue's own task: a ``gather`` that
    spanned both returns with its slowest member, which is how a slow merchant
    endpoint became the fulfilment queue's polling period.

    No coordination between drainers by design: ``FOR UPDATE SKIP LOCKED``
    makes their claims disjoint, so the only thing parallelism changes is that
    a supplier (or a merchant's server) that hangs for 20s stalls one drainer
    instead of the whole queue.

    ``return_exceptions=True`` is what makes "each drainer is isolated"
    literally true. ``_drain_until_dry`` handles what happens *inside* the
    drain, but its own cleanup can still raise -- a ``rollback`` or the
    session ``__aexit__`` on a connection that died. A bare ``gather``
    re-raises that immediately and abandons the sibling drainers mid-task,
    taking the whole tick down with one bad connection.
    """
    results = await asyncio.gather(
        *(_drain_until_dry(session_factory, queue) for _ in range(queue.concurrency)),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            # Type + first line only, never repr(): a SQLAlchemy error
            # stringifies with the statement and its bound parameters, and
            # those go to Loki (AGENTS.md §9). Same discipline as
            # ``fulfillment.service._crash_detail``.
            message = str(result).strip().splitlines()
            log.error(
                "worker.consumer.drainer_crashed",
                queue=queue.name,
                error=f"{type(result).__name__}: {message[0] if message else ''}"[:200],
            )


async def _queue_loop(
    session_factory: async_sessionmaker[AsyncSession],
    queue: Queue,
    *,
    listener: ListenerManager,
    wake: asyncio.Event,
    stop: asyncio.Event,
    poll_seconds: float,
) -> None:
    """One queue's whole life: wake, drain, repeat, until told to stop.

    Each queue gets one of these as its **own task**. That is the fix for a
    real coupling rather than a tidiness preference: with both queues drained
    inside one awaited ``gather``, the call returned only when the slowest
    drainer of either queue did, so the webhook drain's duration became the
    fulfilment queue's polling period. Measured with fakes, a 3 s webhook drain
    cut fulfilment drains in a 6 s window from 116 to 8; the real shape is a
    re-enabled hook with a large backlog against a slow-but-healthy merchant,
    which can drain for hours with every paid order waiting behind it.

    The listener is ensured here, once per iteration, for the same reason it
    always was: no backoff on a failed LISTEN, because the fixed poll tick IS
    the retry cadence and the queue's actual guarantee of progress. A LISTEN
    connection can also go stale silently -- nothing keepalives it -- in which
    case wake-ups stop arriving and the tick is the bound on latency until
    ``ensure()`` notices.

    Args:
        session_factory: Per-drainer session factory.
        queue: What to drain, and how wide.
        listener: This queue's LISTEN connection, re-ensured every iteration.
        wake: This queue's own event. Every listener sets every queue's.
        stop: Shared shutdown signal.
        poll_seconds: The tick.
    """
    while not stop.is_set():
        await listener.ensure()
        await _wait_for_wake_or_tick(wake, stop, seconds=poll_seconds)
        if stop.is_set():
            break
        await _drain_all(session_factory, queue)


async def _await_stray_tasks(*, timeout: float) -> None:
    """Give fire-and-forget work started by the last batch a window to finish.

    ``notifications.schedule`` runs its sends via a bare
    ``asyncio.create_task``; the ones fired by the final commit's
    after-commit hook are still in flight when ``run()`` returns, and
    ``asyncio.run`` cancels every pending task on the way out — the
    customer's "your order is delivered" Telegram message dies with the
    process. Wait for them, bounded; never cancel them (that is exactly the
    bug), and never wait on ourselves.
    """
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        # Logged so a shutdown that sits here for the full window is
        # diagnosable rather than looking like a hang.
        log.info("worker.consumer.awaiting_stray_tasks", count=len(pending))
        await asyncio.wait(pending, timeout=timeout)


async def run() -> None:
    """Start one loop per queue and wait for a stop signal.

    Nothing here is stateful across iterations except the connections
    themselves -- kill the process at any point and the next start (or another
    replica) picks up exactly where the row locks left off.
    """
    cfg = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    queues = _queues(cfg)
    # One event per queue, and every listener sets all of them -- see
    # ``_on_notify`` for why both halves of that sentence matter.
    wakes = tuple(asyncio.Event() for _ in queues)
    dsn = raw_dsn(cfg.database_url)
    listeners = tuple(ListenerManager(dsn, wakes, channel=queue.channel) for queue in queues)
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    log.info(
        "worker.consumer.started",
        poll_seconds=cfg.fulfilment_poll_seconds,
        # Renamed from ``concurrency`` when the second queue landed: nothing in
        # this repo reads it, but a Loki/Grafana panel outside it might.
        queues={queue.name: queue.concurrency for queue in queues},
    )

    loops = [
        asyncio.create_task(
            _queue_loop(
                session_factory,
                queue,
                listener=listener,
                wake=wake,
                stop=stop,
                poll_seconds=cfg.fulfilment_poll_seconds,
            ),
            name=f"drain:{queue.name}",
        )
        for queue, wake, listener in zip(queues, wakes, listeners, strict=True)
    ]

    await stop.wait()
    # Bounded: a loop caught mid-drain finishes its batch if it can, and is
    # otherwise cancelled by ``asyncio.run`` on the way out. Cancelling a drain
    # is safe by construction -- it rolls back an uncommitted batch and its rows
    # go back to ``pending`` (ADR-0064's "loses nothing but row locks").
    _done, still_draining = await asyncio.wait(loops, timeout=SHUTDOWN_DRAIN_SECONDS)
    if still_draining:
        log.info(
            "worker.consumer.shutdown_left_draining",
            queues=[task.get_name() for task in still_draining],
        )

    await _await_stray_tasks(timeout=5.0)
    for listener in listeners:
        await listener.close()
    await close_g2b_pool()
    log.info("worker.consumer.stopped")


if __name__ == "__main__":
    asyncio.run(run())
