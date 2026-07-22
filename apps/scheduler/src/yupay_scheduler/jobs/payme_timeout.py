"""Auto-cancel Payme transactions Payme itself never followed up on.

Payme's Merchant API contract has ``CreateTransaction`` register a pending
transaction (state ``1``) that the buyer is expected to complete on Payme's
own checkout UI within Payme's SLA window. If the buyer abandons that UI and
Payme never calls ``PerformTransaction`` or ``CancelTransaction``, the
transaction — and the ``payments`` row it backs — would sit ``pending``
forever, keeping the order stuck at ``pending_payment`` past any sane
checkout timeout. This sweep reconciles that dead-letter case by cancelling
any state-``1`` transaction older than :data:`TIMEOUT_MS` (12h), the same
state-1-to--1 transition ``payme.service.cancel_transaction`` performs for a
Payme-initiated ``CancelTransaction`` call — just self-driven instead of
provider-driven.

Runs every 5 minutes. Each stale transaction is cancelled in its **own**
session, locked with ``SELECT ... FOR UPDATE`` and re-checked for state
``1`` immediately before writing — a concurrent ``PerformTransaction`` or
``CancelTransaction`` webhook may have already moved it (to ``2`` performed
or ``-1``/``-2`` cancelled) between the listing query and this tick picking
it up, and such a row must be left alone rather than clobbered back to
``-1``. This mirrors ``waxpeer_reconcile.py``'s own-session-per-item
isolation: one bad row (a transient DB hiccup, an unexpected state) can never
abort the batch and leave the rest of the backlog stuck too.

Importing ``payme.models``/``payments.service`` directly (never
``payme.api``/``payme.routes``) avoids the api → routes → api/v1 circular
import ``waxpeer_reconcile.py`` documents for ``fulfillment.api`` — but
``payments.service`` carries a *different*, unavoidable cycle of its own: it
imports ``wallet.api`` → ``wallet.routes`` → ``yupay.api.v1.deps``, which on
a cold import triggers ``yupay.api.v1``'s ``__init__`` to run for the first
time, which imports ``payments.api`` → ``payments.service`` while the latter
is still mid-import, and blows up on a name not yet defined. Priming
``yupay.api.v1`` as a fully-resolved module *before* anything reaches into
``payments.service`` (the same fix ``test_payme_service.py`` uses) makes the
later, nested import of it a cheap ``sys.modules`` hit instead of a second,
partial execution.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.payments import service as pay_svc
from yupay.modules.payments.models import Payment

log = get_logger("yupay.scheduler.payme_timeout")

_JOB_ID = "payme.timeout"
_INTERVAL_SECONDS = 300

#: 12 hours, in milliseconds — comfortably past any realistic buyer checkout
#: session on Payme's own UI. A module constant so tests can seed a
#: clearly-old ``create_time`` (or monkeypatch this) without sleeping.
TIMEOUT_MS = 43_200_000

# Payme's own transaction-state encoding (mirrors ``payme.service``).
_STATE_CREATED = 1
_STATE_CANCELLED_PENDING = -1
# Payme's cancellation-reason code for a system-driven timeout.
_TIMEOUT_REASON = 4


def now_ms() -> int:
    """Return the current time as Payme-style epoch milliseconds."""
    return int(now().timestamp() * 1000)


async def _list_stale_transaction_ids() -> list[str]:
    """Return ids of every state-1 transaction older than :data:`TIMEOUT_MS`.

    One read-only session for the whole listing pass — each id is then
    reconciled later in its own session.
    """
    factory = get_session_factory()
    cutoff = now_ms() - TIMEOUT_MS
    async with factory() as session:
        rows = (
            await session.execute(
                select(PaymeTransaction.id).where(
                    PaymeTransaction.state == _STATE_CREATED,
                    PaymeTransaction.create_time < cutoff,
                )
            )
        ).scalars()
        return list(rows)


async def _cancel_one(transaction_id: str) -> None:
    """Cancel a single stale transaction in its own session/transaction.

    Re-checks the row is still state ``1`` under ``FOR UPDATE`` before
    writing — a concurrent Perform/Cancel may have already moved it, in
    which case this is a silent no-op.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        txn = (
            await session.execute(
                select(PaymeTransaction)
                .where(PaymeTransaction.id == transaction_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if txn is None or txn.state != _STATE_CREATED:
            return

        txn.state = _STATE_CANCELLED_PENDING
        txn.reason = _TIMEOUT_REASON
        txn.cancel_time = now_ms()

        if txn.payment_id is not None:
            payment = (
                await session.execute(select(Payment).where(Payment.id == txn.payment_id))
            ).scalar_one()
            await pay_svc.cancel_pending_provider_payment(session, payment=payment, actor="payme")


async def run_payme_timeout() -> None:
    """One scheduler tick: cancel every Payme transaction stuck past the
    12h timeout.

    Failures are isolated per transaction — logged (transaction id + error
    only, never account/key/PII) and skipped — so a single bad row can't
    stop the rest of the sweep.
    """
    transaction_ids = await _list_stale_transaction_ids()
    if not transaction_ids:
        return

    cancelled = 0
    failed = 0
    for transaction_id in transaction_ids:
        try:
            await _cancel_one(transaction_id)
        except Exception as exc:  # noqa: BLE001 -- one bad row must never abort the sweep
            failed += 1
            log.warning(
                "payme_timeout.transaction_failed", transaction_id=transaction_id, error=str(exc)
            )
        else:
            cancelled += 1

    log.info(
        "payme_timeout.tick",
        checked=len(transaction_ids),
        cancelled=cancelled,
        failed=failed,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_payme_timeout,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("payme_timeout.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["TIMEOUT_MS", "register", "run_payme_timeout"]
