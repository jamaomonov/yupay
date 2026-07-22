"""Fail Uzum Bank transactions Uzum itself never followed up on.

Uzum's Merchant API contract has ``/create`` register a pending transaction
(status ``CREATED``) that the buyer is expected to complete on Uzum's own
checkout UI, which then calls back with ``/confirm``. Per Uzum's spec §10, if
no ``/confirm`` arrives within 30 minutes of ``create_time`` the transaction
is considered unsuccessful. If we never reconciled that ourselves, the
transaction — and the ``payments`` row it backs — would sit ``pending``
forever, keeping the order stuck at ``pending_payment`` past any sane
checkout timeout. This sweep reconciles that dead-letter case by failing any
``CREATED`` transaction older than :data:`TIMEOUT_MS` (30 min): status ->
``FAILED``, backing payment -> cancelled via the same
``cancel_pending_provider_payment`` hook ``uzum.service.reverse`` uses for a
CREATED-state ``/reverse`` — just self-driven instead of provider-driven.

Runs every 5 minutes. Each stale transaction is failed in its **own**
session, locked with ``SELECT ... FOR UPDATE`` and re-checked for status
``CREATED`` immediately before writing — a concurrent ``/confirm`` or
``/reverse`` webhook may have already moved it (to ``CONFIRMED`` or
``REVERSED``) between the listing query and this tick picking it up, and such
a row must be left alone rather than clobbered back to ``FAILED``. This
mirrors ``payme_timeout.py``'s own-session-per-item isolation: one bad row (a
transient DB hiccup, an unexpected status) can never abort the batch and
leave the rest of the backlog stuck too.

**Money-safety invariant**: this job must ONLY ever cancel a payment that is
still ``pending`` when it fails a ``CREATED`` transaction.
``cancel_pending_provider_payment`` cancels a pending payment with no ledger
reversal — correct for an unconfirmed transaction, wrong for a settled one. A
``CONFIRMED`` transaction (payment already ``succeeded``) is never in scope
of the listing query below, and the per-row status re-check guards against a
race that would otherwise let a just-confirmed row slip through -- BUT the
transaction being CREATED does *not* guarantee its *payment* is still
pending: ``uzum.service._ensure_payment`` reuses one order's pending ``uzum``
payment across every ``/create`` call for that order (a customer retrying
checkout), so a sibling transaction sharing this same payment may already
have confirmed it (-> succeeded, order -> paid) while this row is still
``CREATED``. So ``_fail_one`` re-checks the *payment's* status too and only
cancels it while still ``pending``, always failing the transaction either
way. ``uzum.service.reverse`` applies the identical guard when it routes a
CREATED/FAILED transaction into its own cancel-pending branch: a shared
payment a sibling has already settled is left untouched there as well.

Importing ``uzum.models``/``payments.service`` directly (never
``uzum.api``/``uzum.routes``) avoids the api -> routes -> api/v1 circular
import ``waxpeer_reconcile.py`` documents for ``fulfillment.api`` — but
``payments.service`` carries a *different*, unavoidable cycle of its own: it
imports ``wallet.api`` -> ``wallet.routes`` -> ``yupay.api.v1.deps``, which on
a cold import triggers ``yupay.api.v1``'s ``__init__`` to run for the first
time, which imports ``payments.api`` -> ``payments.service`` while the latter
is still mid-import, and blows up on a name not yet defined. Priming
``yupay.api.v1`` as a fully-resolved module *before* anything reaches into
``payments.service`` (the same fix ``payme_timeout.py`` and
``test_uzum_service.py`` use) makes the later, nested import of it a cheap
``sys.modules`` hit instead of a second, partial execution.
"""

from __future__ import annotations

import yupay.api.v1  # noqa: F401  isort: skip

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.payments import service as pay_svc
from yupay.modules.payments.models import Payment
from yupay.modules.uzum.models import UzumTransaction

log = get_logger("yupay.scheduler.uzum_timeout")

_JOB_ID = "uzum.timeout"
_INTERVAL_SECONDS = 300

#: 30 minutes, in milliseconds — Uzum's own spec (§10) SLA for an unconfirmed
#: transaction. A module constant so tests can seed a clearly-old
#: ``create_time`` (or monkeypatch this) without sleeping.
TIMEOUT_MS = 1_800_000

# Uzum's own transaction-status encoding (mirrors ``uzum.service``).
_STATUS_CREATED = "CREATED"
_STATUS_FAILED = "FAILED"


def now_ms() -> int:
    """Return the current time as Uzum-style epoch milliseconds."""
    return int(now().timestamp() * 1000)


async def _list_stale_transaction_ids() -> list[str]:
    """Return ids of every CREATED transaction older than :data:`TIMEOUT_MS`.

    One read-only session for the whole listing pass — each id is then
    reconciled later in its own session.
    """
    factory = get_session_factory()
    cutoff = now_ms() - TIMEOUT_MS
    async with factory() as session:
        rows = (
            await session.execute(
                select(UzumTransaction.id).where(
                    UzumTransaction.status == _STATUS_CREATED,
                    UzumTransaction.create_time < cutoff,
                )
            )
        ).scalars()
        return list(rows)


async def _fail_one(transaction_id: str) -> None:
    """Fail a single stale transaction in its own session/transaction.

    Re-checks the row is still ``CREATED`` under ``FOR UPDATE`` before
    writing — a concurrent ``/confirm`` or ``/reverse`` may have already
    moved it, in which case this is a silent no-op.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        txn = (
            await session.execute(
                select(UzumTransaction)
                .where(UzumTransaction.id == transaction_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if txn is None or txn.status != _STATUS_CREATED:
            return

        txn.status = _STATUS_FAILED

        if txn.payment_id is not None:
            payment = (
                await session.execute(select(Payment).where(Payment.id == txn.payment_id))
            ).scalar_one()
            # ``uzum.service._ensure_payment`` reuses one order's pending
            # ``uzum`` payment across every ``/create`` call for that order,
            # so a sibling transaction may already have confirmed this SAME
            # payment (-> succeeded, order -> paid) while this stale row still
            # sits CREATED. Only cancel while the payment is still pending —
            # cancelling an already-succeeded payment would corrupt a paid
            # (possibly delivered) order and brick ``refund_admin``. If a
            # sibling owns the payment's terminal state, leave it untouched;
            # this transaction still fails either way.
            if payment.status == "pending":
                await pay_svc.cancel_pending_provider_payment(
                    session, payment=payment, actor="uzum"
                )


async def run_uzum_timeout() -> None:
    """One scheduler tick: fail every Uzum transaction stuck past the
    30-minute unconfirmed-transaction timeout.

    Failures are isolated per transaction — logged (transaction id + error
    only, never account/key/PII) and skipped — so a single bad row can't stop
    the rest of the sweep.
    """
    transaction_ids = await _list_stale_transaction_ids()
    if not transaction_ids:
        return

    failed = 0
    errored = 0
    for transaction_id in transaction_ids:
        try:
            await _fail_one(transaction_id)
        except Exception as exc:  # noqa: BLE001 -- one bad row must never abort the sweep
            errored += 1
            log.warning(
                "uzum_timeout.transaction_failed", transaction_id=transaction_id, error=str(exc)
            )
        else:
            failed += 1

    log.info(
        "uzum_timeout.tick",
        checked=len(transaction_ids),
        failed=failed,
        errored=errored,
    )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_uzum_timeout,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once — don't burst-replay.
    )
    log.info("uzum_timeout.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["TIMEOUT_MS", "register", "run_uzum_timeout"]
