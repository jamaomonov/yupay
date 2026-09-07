"""When this process stops, and how much time it may spend stopping.

Split out of :mod:`.consumer` at AGENTS §6's 500-line line — the same ruling
this milestone applied to ``admin_routes.py`` and to ``webhook_delivery.py``.
The seam is a real one: everything here is about the *end* of the process and
knows nothing about queues, listeners or Postgres. What is left in
:mod:`.consumer` is the queues themselves.

Two things live here.

**Supervision** — :func:`supervise` — answers *when* to stop: either something
told us to, or a queue loop died. That second case is not hypothetical
bookkeeping. Before the queues were given their own tasks, an exception in the
drain propagated out of a directly-awaited call and killed the process, which
``restart: unless-stopped`` then restarted; putting each queue in a task turned
that crash into a silent leak, and the crash *was* the monitoring. A loop that
dies must therefore produce a log line and a non-zero exit.

**The budget** — :data:`SHUTDOWN_BUDGET_SECONDS` and everything under it —
answers *how long*. It is one budget for the whole path, spent in order, because
two independent five-second waits added up to exactly Docker's default
``stop_grace_period`` and the tail of the shutdown was being SIGKILLed away.

The logger is deliberately still ``yupay.worker.consumer``: the event names are
the contract a Loki or Grafana panel outside this repo reads, and moving code
between files is not a reason to move a ``logger`` field under them.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Collection, Sequence
from typing import Final

from yupay.core.logging import get_logger

log = get_logger("yupay.worker.consumer")


#: Total wall clock the whole shutdown path may spend, from the stop signal to
#: the last log line. It is a **budget**, shared by the two waits below, and it
#: is 8 and not 10 because Docker's default ``stop_grace_period`` is 10 s and
#: neither compose file overrides it for ``worker``: a shutdown that spends the
#: whole grace period is SIGKILLed with ``close_g2b_pool()`` and
#: ``worker.consumer.stopped`` still to come. Raising this past the grace
#: period means setting ``stop_grace_period`` in both compose files first.
SHUTDOWN_BUDGET_SECONDS: Final = 8.0

#: The budget's first slice: how long a queue loop caught mid-drain gets before
#: the runtime cancels it. A cancelled drain rolls back its uncommitted batch,
#: so the cost is re-doing that batch, never losing it — while a fire-and-forget
#: Telegram send that gets cancelled is a customer who is never told their order
#: is ready, which is why the remainder goes to the strays and not the reverse.
SHUTDOWN_DRAIN_SECONDS: Final = 3.0


async def await_stray_tasks(
    *, timeout: float, exclude: Collection[asyncio.Task[None]] = ()
) -> None:
    """Give fire-and-forget work started by the last batch a window to finish.

    ``notifications.schedule`` runs its sends via a bare
    ``asyncio.create_task``; the ones fired by the final commit's
    after-commit hook are still in flight when ``run()`` returns, and
    ``asyncio.run`` cancels every pending task on the way out — the
    customer's "your order is delivered" Telegram message dies with the
    process. Wait for them, bounded; never cancel them (that is exactly the
    bug), and never wait on ourselves.

    ``exclude`` is the queue loops, and it is not an optimisation: they are
    ``all_tasks()`` too now, so without it a loop still draining after its own
    bounded wait spends the stray window **again** — the two budgets became one
    10-second total, which is exactly Docker's grace period.

    Args:
        timeout: What is left of :data:`SHUTDOWN_BUDGET_SECONDS`.
        exclude: Tasks the caller has already waited on by name.
    """
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and t not in exclude]
    if pending:
        # Logged so a shutdown that sits here for the full window is
        # diagnosable rather than looking like a hang.
        log.info("worker.consumer.awaiting_stray_tasks", count=len(pending))
        await asyncio.wait(pending, timeout=timeout)


async def supervise(loops: Sequence[asyncio.Task[None]], *, stop: asyncio.Event) -> bool:
    """Wait until a queue loop dies or we are told to stop. Report which.

    Without this, ``run()`` awaited only ``stop`` and nothing ever looked at
    the loop tasks: a loop that raised left the process **up, healthy-looking
    and one queue short**, with no log line, no non-zero exit and nothing for
    ``restart: unless-stopped`` to restart — only a GC-time "Task exception was
    never retrieved" on stderr. Before the queues were decoupled the same
    escape propagated out of ``run()`` and killed the process, so giving each
    queue its own task also removed the crash that made a dead queue visible.
    The probability is low (``ensure()`` swallows every ``Exception`` and
    ``_drain_all`` gathers with ``return_exceptions=True``) and the consequence
    is the whole outage: all fulfilment stopped, ``worker.consumer.started``
    still standing.

    A loop that *returns* without ``stop`` being set is treated exactly the
    same. :func:`_queue_loop` has one exit and it is the stop signal, so a
    return is the same dead queue by a quieter route.

    Args:
        loops: One task per queue.
        stop: The shared shutdown signal, set here when a loop dies so the
            surviving loops wind down with it.

    Returns:
        Whether a loop died. The caller turns that into a non-zero exit.
    """
    stopper = asyncio.create_task(stop.wait(), name="worker.stop")
    try:
        await asyncio.wait([*loops, stopper], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stopper
    if stop.is_set():
        return False  # an ordinary shutdown; the loops wind themselves down
    for task in loops:
        if not task.done() or task.cancelled():
            continue
        error = task.exception()  # also marks it retrieved, so no GC-time noise
        log.error(
            "worker.consumer.queue_loop_died",
            queue=task.get_name(),
            # Type + first line only, never repr(): a SQLAlchemy error
            # stringifies with its statement and bound parameters (AGENTS §9).
            error=error_detail(error) if error is not None else "returned without a stop signal",
        )
    stop.set()
    return True


def error_detail(exc: BaseException) -> str:
    """``Type: first line``, the shape ``fulfillment.service._crash_detail`` uses."""
    message = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {message[0] if message else ''}"[:200]


def remaining(deadline: float) -> float:
    """Seconds left on a monotonic deadline, never negative."""
    return max(0.0, deadline - time.monotonic())


__all__ = [
    "SHUTDOWN_BUDGET_SECONDS",
    "SHUTDOWN_DRAIN_SECONDS",
    "await_stray_tasks",
    "error_detail",
    "remaining",
    "supervise",
]
