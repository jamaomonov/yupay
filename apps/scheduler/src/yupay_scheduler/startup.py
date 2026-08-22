"""When a periodic job should first fire after the process starts.

APScheduler's ``interval`` trigger, given no ``next_run_time``, schedules the
first run one whole interval after ``add_job``. For a job that runs every
minute that is invisible. For an hourly one it means every restart pushes the
next run a full hour out — so a container that restarts more often than its
own period never runs the job at all, silently, with the scheduler up and the
job listed as registered.

That is not hypothetical: a deploy restarts every container, and the daily
evidence purge needs only one restart per day to never happen.

So a long-period job gets an explicit first run shortly after boot. The delays
are staggered rather than shared: several of these jobs call the same supplier
APIs, and firing them together on every deploy turns a restart into a burst.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def first_run_after(seconds: int) -> datetime:
    """A ``next_run_time`` ``seconds`` from now.

    Deliberately not "now": a container that crash-loops faster than this
    would otherwise re-run the job on every attempt, and these jobs talk to
    paid upstreams.
    """
    return datetime.now(UTC) + timedelta(seconds=seconds)


__all__ = ["first_run_after"]
