"""Every supplier that can leave an order in flight has a sweep watching it.

This is the test that would have caught FazerCards shipping without one.
Everything else about that integration was in place — adapter registered,
mappings seeded, catalogue synced, webhook receiving — and an order routed to
it would still have hung forever, because their create answers ``processing``
and nothing was going to ask what happened next.

The failure mode is silent and expensive in exactly the way a missing sweep
always is: no error, no alert, a customer on "в обработке" and money already
spent upstream. A list nobody checks is how it happens, so the list is checked
here rather than in a reviewer's head.
"""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay_scheduler.main import build_scheduler

#: Suppliers whose orders can sit ``in_progress`` after a successful create,
#: and therefore need somebody to poll. A fulfiller that answers terminally on
#: the spot does not belong here — `manual` waits on an operator, `mock` and
#: the stubs never call anyone.
NEEDS_A_SWEEP = ("g2b", "gengine", "nova", "fzr", "waxpeer")


@pytest.fixture
def _scheduler() -> AsyncIOScheduler:
    """A built, unstarted scheduler. Registration happens at build time."""
    return build_scheduler()


@pytest.mark.parametrize("slug", NEEDS_A_SWEEP)
def test_each_supplier_has_a_registered_reconcile_job(
    _scheduler: AsyncIOScheduler, slug: str
) -> None:
    ids = {job.id for job in _scheduler.get_jobs()}
    assert f"fulfillment.{slug}_reconcile" in ids, (
        f"{slug} has no reconcile sweep: an order it leaves in_progress would "
        "never be looked at again"
    )


def test_the_panel_vendors_share_one_sweep_but_keep_separate_jobs(
    _scheduler: AsyncIOScheduler,
) -> None:
    """NOVA and FazerCards run the same code (ADR-0092) on separate schedules.

    One job for both would poll one vendor's backlog under the other's name and
    make the logs unreadable; one implementation for both is the point of the
    shared module. This pins that it is two jobs, not one.
    """
    ids = {job.id for job in _scheduler.get_jobs()}
    assert "fulfillment.nova_reconcile" in ids
    assert "fulfillment.fzr_reconcile" in ids


def test_no_reconcile_job_can_stack_on_a_slow_tick(_scheduler: AsyncIOScheduler) -> None:
    """``max_instances=1`` and ``coalesce`` on every sweep.

    Without them a tick that outruns its interval starts a second one against
    the same backlog, and two reconcilers racing one task is how a single
    order gets asked about — and acted on — twice.
    """
    for slug in NEEDS_A_SWEEP:
        job = _scheduler.get_job(f"fulfillment.{slug}_reconcile")
        assert job is not None, slug
        assert job.max_instances == 1, slug
        assert job.coalesce is True, slug
