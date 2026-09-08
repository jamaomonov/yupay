"""What one delivery attempt did — to the row, and to the hook's health.

Split out of :mod:`.webhook_delivery` because that file passed AGENTS §6's
500-line line. The seam is the one its own concern named: everything here runs
**after** the request comes back (or fails to), and touches no socket. What is
left there claims rows, signs them and sends them.

## The row is a log, not bookkeeping

Every attempt appends to ``merchant_webhook_deliveries``: the status their
server answered, the first :data:`~.models.WEBHOOK_RESPONSE_BODY_MAX`
characters of their body, our own ``last_error``, and the attempt count. From
M4 a support engineer answers "they say the 14:02 event never arrived" by
reading one row, so the ``response_body`` of a *failure* is worth as much as
the code. Both text columns are **length-bounded in the schema**, and
:func:`_clip` truncates to the same constants — a forgotten clip is then a loud
``DataError`` on the delivery row rather than a silent wrong value.

## Auto-disable

A failure that is the merchant's (their server, their configuration) increments
``failure_streak``; any success resets it. At
``merchant_webhook_disable_after_failures`` the hook's ``disabled_at`` is set
and their operator is emailed — **once per disable**, never once per attempt,
which is what :class:`DisableNotice` exists to make true: the decision is
returned out of the per-row savepoint rather than acted on inside it.

Nothing is deleted and nothing is thrown away: queued rows stay ``pending`` and
are simply not claimed while the hook is off, so
``PUT /admin/merchants/{id}/webhook`` (which clears ``disabled_at`` and the
streak) resumes the backlog. That is the only recovery path; there is no second
one.

One failure never reaches that budget: :class:`~yupay.core.outbound_errors.
OutboundBrokenError` means the attempt broke in a way neither side chose — our
bug. Counting it would auto-disable a working endpoint and tell the merchant,
in the log they read, that we refused their URL. The same is true of an
unexpected exception caught by the drain's poison belt
(:func:`fail_after_crash`), which deliberately leaves the hook alone.

## What is never written here

The secret and the signature. The delivery **URL** is not logged either — a
webhook path can carry a token — though it is stored on the row, which is the
merchant's own record of their own endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from sqlalchemy import select

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.core.outbound import OutboundResponse
from yupay.modules.merchants import webhook_retry
from yupay.modules.merchants.models import (
    WEBHOOK_LAST_ERROR_MAX,
    WEBHOOK_RESPONSE_BODY_MAX,
    MerchantUser,
    MerchantWebhook,
    MerchantWebhookDelivery,
)
from yupay.modules.notifications.api import schedule_after_commit
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import merchant_webhook_disabled_email

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.merchants.webhook_outcome")


@dataclass(frozen=True, slots=True)
class DisableNotice:
    """One auto-disable that has just happened and needs announcing.

    Returned out of the per-row savepoint rather than acted on inside it: an
    email scheduled from within a savepoint that then rolls back would announce
    a disable that never happened.
    """

    merchant_id: str
    host: str
    failures: int
    last_error: str


async def record(
    db: AsyncSession,
    *,
    delivery: MerchantWebhookDelivery,
    decision: webhook_retry.Decision,
    at: datetime,
    response: OutboundResponse | None,
    error: str | None,
) -> DisableNotice | None:
    """Write one attempt's outcome onto the row and onto the hook's health.

    Both text columns are truncated **here**, before the write, because they
    are length-bounded in the schema: forgetting is a ``DataError`` on the
    delivery row, which is the loud failure Task 1 chose on purpose.
    """
    delivery.response_code = response.status_code if response is not None else None
    delivery.response_body = (
        _clip(response.body, WEBHOOK_RESPONSE_BODY_MAX) if response is not None else None
    )
    delivery.last_error = _clip(error, WEBHOOK_LAST_ERROR_MAX) if error else None

    if decision.outcome is webhook_retry.Outcome.DELIVERED:
        delivery.status = "delivered"
        await _record_success(db, merchant_id=delivery.merchant_id, at=at)
        log.info(
            "merchant_webhook.delivered",
            delivery_id=delivery.id,
            merchant_id=delivery.merchant_id,
            event_type=delivery.event_type,
            status_code=delivery.response_code,
            attempts=delivery.attempts_count,
            # Where the delivery went. AGENTS §9's never-log list says "IP"
            # flatly, so this is one of three named carve-outs written into
            # that section rather than an exception argued only here. The test
            # there is *who chose the endpoint*: this is an address the
            # merchant published to us as a destination, not one we observed a
            # person arriving from — and "we recorded a 200 — to which of their
            # hosts?" is the delivery log's whole question.
            address=response.address if response is not None else None,
        )
        await db.flush()
        return None

    if decision.outcome is webhook_retry.Outcome.RETRY:
        delivery.status = "pending"
        delivery.next_attempt_at = at + timedelta(seconds=decision.delay_seconds)
    else:
        delivery.status = "failed"
    log.warning(
        "merchant_webhook.attempt_failed",
        delivery_id=delivery.id,
        merchant_id=delivery.merchant_id,
        event_type=delivery.event_type,
        status_code=delivery.response_code,
        attempts=delivery.attempts_count,
        outcome=str(decision.outcome),
        error=delivery.last_error,
    )
    notice: DisableNotice | None = None
    if decision.counts_toward_streak:
        notice = await _record_failure(
            db,
            merchant_id=delivery.merchant_id,
            at=at,
            error=delivery.last_error or "",
        )
    await db.flush()
    return notice


async def _record_success(db: AsyncSession, *, merchant_id: str, at: datetime) -> None:
    """A delivered event clears the streak. Any success, not a run of them."""
    hook = await _lock_hook(db, merchant_id)
    if hook is None:  # pragma: no cover -- the claim joined it
        return
    hook.failure_streak = 0
    hook.last_success_at = at


async def _record_failure(
    db: AsyncSession, *, merchant_id: str, at: datetime, error: str
) -> DisableNotice | None:
    """Count one failure against the merchant, and disable at the threshold.

    Returns:
        A notice when *this* call did the disabling — which is what makes the
        email exactly one per disable rather than one per failed attempt. The
        hook row is locked for the read-modify-write, so two drainers cannot
        both cross the threshold.
    """
    hook = await _lock_hook(db, merchant_id)
    if hook is None:  # pragma: no cover -- the claim joined it
        return None
    hook.failure_streak += 1
    hook.last_failure_at = at
    threshold = get_settings().merchant_webhook_disable_after_failures
    if hook.failure_streak < threshold or hook.disabled_at is not None:
        return None
    hook.disabled_at = at
    log.error(
        "merchant_webhook.auto_disabled",
        merchant_id=merchant_id,
        failures=hook.failure_streak,
        error=error,
    )
    return DisableNotice(
        merchant_id=merchant_id,
        # The host, not the URL: a webhook path can carry a token, and this
        # string goes into an email.
        host=urlsplit(hook.url).hostname or "",
        failures=hook.failure_streak,
        last_error=error,
    )


async def _lock_hook(db: AsyncSession, merchant_id: str) -> MerchantWebhook | None:
    """The hook row, locked and refreshed, for a read-modify-write.

    ``populate_existing`` matters: the same row was read (unlocked) to decrypt
    the secret before the HTTP call, and without it SQLAlchemy would hand back
    that stale copy and increment a ``failure_streak`` read minutes ago.

    The lock is taken **after** the request, never before, so it is held for a
    flush rather than across a merchant's ten-second timeout. Two deliveries to
    the same endpoint therefore serialise at commit; that is a feature — it
    bounds how hard one queue can hit one server — and the merchant-major
    ordering in :func:`_merchant_major` is what keeps it deadlock-free.
    """
    return (
        await db.execute(
            select(MerchantWebhook)
            .where(MerchantWebhook.merchant_id == merchant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def announce_disable(db: AsyncSession, notice: DisableNotice) -> None:
    """Email the merchant's operators that we stopped delivering. Once.

    Scheduled through the notifications module's own after-commit hook, so it
    cannot announce a disable the worker's transaction goes on to roll back,
    and it never blocks the drain. A merchant with no operator row is disabled
    silently: a send with no recipient is not a reason to keep hammering an
    endpoint that has been failing for hours.
    """
    recipients = list(
        (
            await db.execute(
                select(MerchantUser.email).where(MerchantUser.merchant_id == notice.merchant_id)
            )
        ).scalars()
    )
    if not recipients:
        log.warning("merchant_webhook.disable_unannounced", merchant_id=notice.merchant_id)
        return
    for email in recipients:
        # ``partial`` and not a closure over the loop variable: the hook wants a
        # zero-argument factory, and a ``lambda: _send_disabled_email(email, …)``
        # would late-bind ``email`` to whatever the loop ended on, mailing the
        # last operator once per operator. It also types exactly as
        # ``Callable[[], Coroutine[Any, Any, bool]]``, so no ``type: ignore``.
        schedule_after_commit(db, partial(_send_disabled_email, email, notice))


async def _send_disabled_email(email: str, notice: DisableNotice) -> bool:
    """Send one auto-disable notice. Never raises; the recipient is never logged."""
    content = merchant_webhook_disabled_email(
        host=notice.host, failures=notice.failures, last_error=notice.last_error
    )
    try:
        await send_email(to=email, subject=content.subject, html=content.html, text=content.text)
    except EmailSendError:
        log.warning("merchant_webhook.disable_email_failed", merchant_id=notice.merchant_id)
        return False
    return True


async def fail_after_crash(db: AsyncSession, *, delivery_id: str, error: BaseException) -> None:
    """Mark a row whose attempt crashed unexpectedly, in the outer transaction.

    The savepoint has already rolled back this row's writes and expired the
    objects it touched, so the row is re-read; the claim's ``FOR UPDATE`` lock
    is held by the outer transaction and is unaffected by a savepoint rollback,
    so nothing else can have touched it meanwhile.

    The hook is deliberately untouched: an unexpected exception here is ours,
    and ours must never reach a merchant's failure budget.
    """
    summary = detail(error)
    delivery = await load_delivery(db, delivery_id)
    delivery.status = "failed"
    delivery.attempts_count += 1
    delivery.last_error = _clip(summary, WEBHOOK_LAST_ERROR_MAX)
    log.error(
        "merchant_webhook.attempt_crashed",
        delivery_id=delivery_id,
        merchant_id=delivery.merchant_id,
        error=summary[:200],
    )


async def load_delivery(db: AsyncSession, delivery_id: str) -> MerchantWebhookDelivery:
    """Re-read a claimed delivery row by id."""
    return (
        await db.execute(
            select(MerchantWebhookDelivery).where(MerchantWebhookDelivery.id == delivery_id)
        )
    ).scalar_one()


def detail(exc: BaseException) -> str:
    """``Type: first line``, the shape ``fulfillment.service._crash_detail`` uses.

    Not ``repr`` and never the chain: a SQLAlchemy error stringifies with its
    statement and bound parameters, and ``core.outbound`` warns that the
    ``__cause__`` under a transport failure holds the **pinned URL with its
    query** — which is where a merchant's token would be. One line, typed.
    """
    lines = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"


def _clip(text: str, limit: int) -> str:
    """Cut to a column bound. Characters, which is what ``VARCHAR(n)`` counts."""
    return text[:limit]


__all__ = [
    "DisableNotice",
    "announce_disable",
    "detail",
    "fail_after_crash",
    "load_delivery",
    "record",
]
