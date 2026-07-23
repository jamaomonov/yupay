"""Cancel Click Shop API transactions Click itself never followed up on.

Click's Shop API contract has ``/prepare`` register a ``PREPARED`` transaction
that Click is expected to follow up on with ``/complete`` once the customer
finishes paying on ``my.click.uz`` / Click Up. If ``/complete`` never arrives
(buyer abandonment, dropped callback), the transaction — and the ``payments``
row it backs — would sit ``pending`` forever, keeping the order stuck at
``pending_payment`` past any sane checkout window. This sweep reconciles that
dead-letter case by cancelling any ``PREPARED`` transaction whose
``prepare_time`` is older than :data:`TIMEOUT` (default 30 minutes; spec §10 —
open decision §16 #4 flags this as pending Click's own confirmation of the
window): status -> ``CANCELLED``, backing payment -> cancelled via the same
``cancel_pending_provider_payment`` hook the negative-inbound-``error`` path
uses.

Unlike Uzum's ``create_time`` (epoch milliseconds), Click's ``prepare_time``
is a genuine ``timestamptz`` column, so the cutoff here is a ``datetime``
(``now() - TIMEOUT``), not an integer subtraction against epoch-ms.

This job does **not** reimplement the cancel/guard logic: every stale row is
routed through :func:`yupay.modules.click.service.cancel`, keyed by
``merchant_prepare_id`` — the exact same helper the ``/prepare`` negative-
``error`` webhook path uses. ``cancel()`` already re-checks the row is still
``PREPARED`` under ``FOR UPDATE`` immediately before writing (a concurrent
``/complete`` may have already confirmed it between the listing query and this
tick picking it up — left alone rather than clobbered back to ``CANCELLED``)
and only cancels the backing payment while it is still ``pending`` — see the
Money-safety paragraph below. Reusing it here (instead of duplicating its
body, the way ``uzum_timeout.py`` does for ``uzum.service.reverse``) means
this sweep can never drift from that guard.

Runs every 5 minutes, mirroring ``uzum_timeout.py``'s cadence. Each stale
transaction is cancelled in its **own** session — one bad row (a transient DB
hiccup, an unexpected status) can never abort the batch and leave the rest of
the backlog stuck too.

**Money-safety invariant**: this job must ONLY ever cancel a payment that is
still ``pending`` when it cancels a ``PREPARED`` transaction.
``cancel_pending_provider_payment`` cancels a pending payment with no ledger
reversal — correct for an unconfirmed transaction, wrong for a settled one. A
``CONFIRMED`` transaction (payment already ``succeeded``) is never in scope of
the listing query below. But ``PREPARED`` status does *not* guarantee its
*payment* is still pending: ``click.service._ensure_payment`` reuses one
order's pending payment across every ``/prepare`` call for that order/provider
(a customer retrying checkout), so a sibling transaction sharing this same
payment may already have confirmed it (-> succeeded, order -> paid) while this
row is still ``PREPARED``. ``click.service.cancel`` re-checks the *payment's*
status too and only cancels it while still ``pending``, always cancelling the
transaction either way.

Importing ``yupay.api.v1`` first avoids the same ``payments.service`` <->
``wallet.routes`` <-> ``api.v1`` import cycle ``uzum_timeout.py`` documents —
``click.service`` carries the identical cold-import trap since it too reaches
into ``payments.service``.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.click import service as click_svc
from yupay.modules.click.models import ClickTransaction

log = get_logger("yupay.scheduler.click_timeout")

_JOB_ID = "click.timeout"
_INTERVAL_SECONDS = 300

#: 30 minutes — default stale-prepare window (spec §10; §16 open decision #4
#: pending Click's own confirmation). A module constant so tests can seed a
#: clearly-old ``prepare_time`` (or monkeypatch this) without sleeping.
TIMEOUT = timedelta(minutes=30)

# Click's own transaction-status encoding (mirrors ``click.service``).
_STATUS_PREPARED = "PREPARED"


async def _list_stale_prepare_ids() -> list[int]:
    """Return ``merchant_prepare_id``s of every PREPARED transaction older
    than :data:`TIMEOUT`.

    One read-only session for the whole listing pass — each id is then
    reconciled later in its own session via :func:`_cancel_one`.
    """
    factory = get_session_factory()
    cutoff = now() - TIMEOUT
    async with factory() as session:
        rows = (
            await session.execute(
                select(ClickTransaction.merchant_prepare_id).where(
                    ClickTransaction.status == _STATUS_PREPARED,
                    ClickTransaction.prepare_time < cutoff,
                )
            )
        ).scalars()
        return list(rows)


async def _cancel_one(merchant_prepare_id: int) -> None:
    """Cancel a single stale transaction in its own session/transaction.

    Delegates entirely to :func:`yupay.modules.click.service.cancel`, which
    re-checks the row is still ``PREPARED`` under ``FOR UPDATE`` before
    writing (a concurrent ``/complete`` may have already confirmed it, in
    which case this is a silent no-op) and only cancel-pends the backing
    payment while it is still ``pending`` — see the module docstring's
    money-safety paragraph.

    Args:
        merchant_prepare_id: The transaction's own id, as handed back to
            Click at Prepare time.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await click_svc.cancel(session, merchant_prepare_id=merchant_prepare_id)


async def run_click_timeout() -> None:
    """One scheduler tick: cancel every Click transaction stuck past the
    30-minute stale-prepare timeout.

    Failures are isolated per transaction — logged (``merchant_prepare_id`` +
    error only, never account/key/PII) and skipped — so a single bad row
    can't stop the rest of the sweep.
    """
    prepare_ids = await _list_stale_prepare_ids()
    if not prepare_ids:
        return

    cancelled = 0
    errored = 0
    for merchant_prepare_id in prepare_ids:
        try:
            await _cancel_one(merchant_prepare_id)
        except Exception as exc:  # noqa: BLE001 -- one bad row must never abort the sweep
            errored += 1
            log.warning(
                "click_timeout.transaction_failed",
                merchant_prepare_id=merchant_prepare_id,
                error=str(exc),
            )
        else:
            cancelled += 1

    log.info(
        "click_timeout.tick",
        checked=len(prepare_ids),
        cancelled=cancelled,
        errored=errored,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_click_timeout,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("click_timeout.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["TIMEOUT", "register", "run_click_timeout"]
