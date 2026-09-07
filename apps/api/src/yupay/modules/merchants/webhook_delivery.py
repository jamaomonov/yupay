"""The webhook outbox's **consumer** — sign it, send it, write down what happened.

Spec §10, M3a Task 4. :mod:`.webhooks` fills the outbox in the transaction that
causes each event; this module drains it from ``apps/worker``, in exactly the
shape ``fulfillment.service.drain_pending_tasks`` established (ADR-0064): claim
with ``FOR UPDATE SKIP LOCKED``, one ``SAVEPOINT`` per row, never commit —
the worker owns the transaction and commits after every batch.

The retry table itself is :mod:`.webhook_retry`, which is pure and has no idea
a database exists. What lives here is the I/O and the writing.

## The row is a log, not bookkeeping

Every attempt appends to ``merchant_webhook_deliveries``: the status their
server answered, the first :data:`~.models.WEBHOOK_RESPONSE_BODY_MAX`
characters of their body, our own ``last_error``, and the attempt count. From
M4 a support engineer answers "they say the 14:02 event never arrived" by
reading one row, so the ``response_body`` of a *failure* is worth as much as
the code. Both text columns are **length-bounded in the schema**, and callers
truncate to the same constants — a forgotten clip is then a loud ``DataError``
on the delivery row rather than a silent wrong value.

## Ordering

The claim orders by ``next_attempt_at, created_at, id``. The third term is not
decoration: both timestamps default to ``CURRENT_TIMESTAMP``, which in Postgres
is the **transaction start**, so the ``paid`` and ``fulfilling`` rows one
merchant placement enqueues are byte-identical in both columns and an ORDER BY
over them alone picks arbitrarily. ``id`` is a uuid7, so it encodes enqueue
order exactly. Without it a reseller can receive ``fulfilling`` before ``paid``
and read the later ``paid`` as a status regression, re-opening an order their
back office already closed.

That fixes the tie. It does **not** make delivery globally ordered: a retried
event lands after events enqueued behind it, which is inherent to per-row
backoff. Receivers order by the payload's ``at`` and dedupe on the delivery id.

Within a batch, rows are processed **merchant by merchant, merchants in id
order**. Two concurrent drainers claim disjoint delivery rows but both write
the *hook* row of any merchant they touch, and taking those locks in a
consistent global order is what stops an AB/BA deadlock between them.

## At-least-once, and the handle that makes it usable

A ``Delivery.UNKNOWN`` failure — a timeout, an exchange that broke mid-flight —
may already have been processed by the merchant. We retry anyway, because that
is what a webhook is; what makes it *actionable* is that the delivery row's id
is stable across every retry of that row, travels in ``X-Yupay-Delivery`` and
is inside the **signed** material (:mod:`.signing`). An unsigned header would
be worthless against a replay, and after the first integrator this could not be
added without a ``/merchant/v2``.

## Auto-disable

A failure that is the merchant's (their server, their configuration) increments
``failure_streak``; any success resets it. At
``merchant_webhook_disable_after_failures`` the hook's ``disabled_at`` is set
and their operator is emailed — **once per disable**, never once per attempt.
Nothing is deleted and nothing is thrown away: queued rows stay ``pending`` and
are simply not claimed while the hook is off, so
``PUT /admin/merchants/{id}/webhook`` (which clears ``disabled_at`` and the
streak) resumes the backlog. That is the only recovery path; there is no
second one.

One failure never reaches that budget: :class:`~yupay.core.outbound_errors.
OutboundBrokenError` means the attempt broke in a way neither side chose — our
bug. Counting it would auto-disable a working endpoint and tell the merchant,
in the log they read, that we refused their URL.

## What is never logged

The secret, the signature, and the body. The secret is decrypted at send time
and lives in one local; the signature authorises the delivery; the body is the
merchant's own event data. The delivery **URL** is not logged either — a
webhook path can carry a token — though it is stored on the row, which is the
merchant's own record of their own endpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from sqlalchemy import select

from yupay.core import crypto
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.core.outbound import OutboundResponse, post_json
from yupay.core.outbound_errors import OutboundError
from yupay.modules.merchants import signing, webhook_retry
from yupay.modules.merchants.models import (
    WEBHOOK_LAST_ERROR_MAX,
    WEBHOOK_RESPONSE_BODY_MAX,
    MerchantUser,
    MerchantWebhook,
    MerchantWebhookDelivery,
)
from yupay.modules.merchants.webhooks import EVENT_TYPES
from yupay.modules.notifications.api import schedule_after_commit
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import merchant_webhook_disabled_email

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.merchants.webhook_delivery")

#: How many rows one claim takes. Matches ``drain_pending_tasks``' default:
#: the worker drains until a batch comes back empty, so this bounds how long
#: one transaction (and therefore one merchant's hook-row lock) is held, not
#: how much work a wake does.
DEFAULT_LIMIT: Final = 20


@dataclass(frozen=True, slots=True)
class _DisableNotice:
    """One auto-disable that has just happened and needs announcing.

    Returned out of the per-row savepoint rather than acted on inside it: an
    email scheduled from within a savepoint that then rolls back would announce
    a disable that never happened.
    """

    merchant_id: str
    host: str
    failures: int
    last_error: str


async def drain_pending_deliveries(db: AsyncSession, *, limit: int = DEFAULT_LIMIT) -> int:
    """Claim and attempt due webhook deliveries. The worker's second job.

    Shaped like ``fulfillment.api.drain_pending_tasks`` down to the details
    that matter: ``FOR UPDATE SKIP LOCKED`` is the whole concurrency story, a
    ``SAVEPOINT`` per row keeps a poisoned delivery from taking the batch with
    it, and nothing here commits — the caller owns the transaction, so a crash
    loses row locks and nothing else.

    A delivery whose hook is disabled is **not claimed** and stays ``pending``:
    re-enabling is what resumes it. See the module docstring.

    Args:
        db: Session. The caller owns the transaction.
        limit: Rows to claim in this batch.

    Returns:
        How many rows this batch claimed. ``0`` means the queue is dry, which
        is the worker's signal to stop draining — so a row skipped because its
        hook went off mid-batch still counts, and the next (now-filtered) claim
        is what ends the loop.
    """
    claimed = await _claim(db, limit=limit)
    ran = 0
    for delivery_id in _merchant_major(claimed):
        notice: _DisableNotice | None = None
        try:
            async with db.begin_nested():
                notice = await _attempt(db, delivery_id=delivery_id)
        except Exception as exc:  # noqa: BLE001 -- a poisoned row must not stall the batch
            # ``post_json`` is total, so an untyped exception here is a bug in
            # *our* recording code, not a transport failure. Without the
            # savepoint it would escape this loop, and since this function
            # never commits, the worker would roll back the whole batch —
            # discarding every delivery already recorded — and leave this row
            # ``pending`` for the next tick to crash on again.
            notice = None  # whatever the savepoint decided is undone
            await _fail_after_crash(db, delivery_id=delivery_id, error=exc)
        if notice is not None:
            await _announce_disable(db, notice)
        ran += 1
    await db.flush()
    return ran


async def _claim(db: AsyncSession, *, limit: int) -> list[tuple[str, str]]:
    """Lock the next due deliveries and return their ``(id, merchant_id)``.

    The join is the enabled-hook filter and nothing else: the row carries its
    own ``url`` snapshot, and the secret is read per attempt. ``of=`` keeps the
    lock on the delivery rows — locking the hook here would hold it across
    every HTTP call in the batch.
    """
    rows = (
        await db.execute(
            select(MerchantWebhookDelivery.id, MerchantWebhookDelivery.merchant_id)
            .join(
                MerchantWebhook,
                MerchantWebhook.merchant_id == MerchantWebhookDelivery.merchant_id,
            )
            .where(
                MerchantWebhookDelivery.status == "pending",
                MerchantWebhookDelivery.next_attempt_at <= now(),
                MerchantWebhook.disabled_at.is_(None),
            )
            .order_by(
                MerchantWebhookDelivery.next_attempt_at,
                MerchantWebhookDelivery.created_at,
                # The tie-break the module docstring exists for.
                MerchantWebhookDelivery.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True, of=MerchantWebhookDelivery)
        )
    ).all()
    return [(delivery_id, merchant_id) for delivery_id, merchant_id in rows]


def _merchant_major(claimed: list[tuple[str, str]]) -> list[str]:
    """Re-order a batch merchant-by-merchant, merchants in id order.

    Two things at once. Each merchant's deliveries keep their claim order, so
    ``paid`` still precedes ``fulfilling``; and every drainer takes hook-row
    locks in the same global order, so two of them working overlapping
    merchants cannot deadlock against each other.
    """
    groups: dict[str, list[str]] = {}
    for delivery_id, merchant_id in claimed:
        groups.setdefault(merchant_id, []).append(delivery_id)
    return [delivery_id for merchant_id in sorted(groups) for delivery_id in groups[merchant_id]]


async def _attempt(db: AsyncSession, *, delivery_id: str) -> _DisableNotice | None:
    """Send one delivery and write the outcome onto its row.

    Args:
        db: Session, inside this row's savepoint.
        delivery_id: The claimed row.

    Returns:
        A notice when this attempt tripped the auto-disable, else ``None``.
    """
    delivery = await _load(db, delivery_id)
    credentials = await _credentials_for(db, delivery.merchant_id)
    if credentials is None:
        # Disabled between the claim and now — by an admin, or by the
        # auto-disable an earlier row of this very batch tripped. The row is
        # left exactly as it was: ``pending``, its backoff untouched, not
        # claimable again until the hook is re-enabled. Delivering to an
        # endpoint we have just switched off is the one thing the switch is
        # for.
        return None
    at = now()
    attempts = delivery.attempts_count + 1
    delivery.attempts_count = attempts
    # The documented FSM (``pending`` → ``in_progress`` → terminal), written
    # for the same reason ``fulfillment.process_task`` writes it. It is not
    # observable outside this transaction, because the claim and the attempt
    # share one: the alternative — committing the claim first — trades "a
    # killed worker retries" for "a killed worker leaves a stuck row somebody
    # has to reap", and a retry is what at-least-once already promises.
    delivery.status = "in_progress"

    if delivery.event_type not in EVENT_TYPES:
        # Nothing can put this in the table today (``enqueue`` refuses it), and
        # the check is here anyway because the canonical string's safety rests
        # on the claim that ``event_type`` is a closed ASCII vocabulary: an
        # event type carrying an LF could move a field boundary.
        return await _record(
            db,
            delivery=delivery,
            decision=webhook_retry.Decision(
                outcome=webhook_retry.Outcome.TERMINAL,
                counts_toward_streak=False,
                delay_seconds=0.0,
            ),
            at=at,
            response=None,
            error=f"unknown event type: {delivery.event_type!r}",
        )

    body = _canonical_body(delivery.payload)
    headers = _signed_headers(secret=credentials, delivery=delivery, body=body, at=at)
    await db.flush()

    try:
        response = await post_json(delivery.url, body=body, headers=headers)
    except OutboundError as exc:
        return await _record(
            db,
            delivery=delivery,
            decision=webhook_retry.decide_failure(exc, attempts=attempts),
            at=at,
            response=None,
            error=_detail(exc),
        )
    decision = webhook_retry.decide_response(
        status_code=response.status_code,
        retry_after=response.retry_after,
        attempts=attempts,
        now=at,
    )
    return await _record(
        db,
        delivery=delivery,
        decision=decision,
        at=at,
        response=response,
        error=(
            None
            if decision.outcome is webhook_retry.Outcome.DELIVERED
            else f"HTTP {response.status_code}"
        ),
    )


def _canonical_body(payload: dict[str, Any]) -> bytes:
    """Serialise the stored payload into the exact bytes we sign and send.

    ``sort_keys`` because JSONB does not preserve key order, so two attempts at
    one row would otherwise put different bytes on the wire; compact separators
    because the merchant hashes what they receive and every byte is signed.
    """
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


async def _credentials_for(db: AsyncSession, merchant_id: str) -> str | None:
    """The decrypted signing secret, or ``None`` if the hook is off by now.

    Columns rather than the entity, deliberately: the hook row is loaded (and
    locked) again when the outcome is recorded, and there is no reason for key
    material to sit in the session's identity map across an HTTP call in
    between.

    The ``disabled_at`` re-read closes the window between the claim and the
    send — the claim's join saw an enabled hook, and an admin (or this batch's
    own auto-disable) may have switched it off since.
    """
    row = (
        await db.execute(
            select(
                MerchantWebhook.disabled_at,
                MerchantWebhook.secret_enc,
                MerchantWebhook.secret_nonce,
            ).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).one_or_none()
    if row is None or row.disabled_at is not None:
        return None
    return crypto.decrypt(row.secret_enc, row.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)


def _signed_headers(
    *, secret: str, delivery: MerchantWebhookDelivery, body: bytes, at: datetime
) -> dict[str, str]:
    """The four headers one delivery carries. Never logged, never stored."""
    timestamp = str(int(at.timestamp()))
    message = signing.webhook_canonical_message(
        timestamp=timestamp,
        delivery_id=delivery.id,
        event_type=delivery.event_type,
        body=body,
    )
    return {
        signing.WEBHOOK_DELIVERY_HEADER: delivery.id,
        signing.WEBHOOK_EVENT_HEADER: delivery.event_type,
        signing.WEBHOOK_TIMESTAMP_HEADER: timestamp,
        signing.WEBHOOK_SIGNATURE_HEADER: signing.expected_signature(secret, message),
    }


async def _record(
    db: AsyncSession,
    *,
    delivery: MerchantWebhookDelivery,
    decision: webhook_retry.Decision,
    at: datetime,
    response: OutboundResponse | None,
    error: str | None,
) -> _DisableNotice | None:
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
            # Their server's address, not a person's (AGENTS §9) — "we
            # recorded a 200, from which of their hosts" is the delivery log's
            # question.
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
    notice: _DisableNotice | None = None
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
) -> _DisableNotice | None:
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
    return _DisableNotice(
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


async def _announce_disable(db: AsyncSession, notice: _DisableNotice) -> None:
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
        schedule_after_commit(db, _sender(email, notice))


def _sender(email: str, notice: _DisableNotice):  # type: ignore[no-untyped-def]
    """Build the zero-arg factory ``schedule_after_commit`` wants.

    Untyped return on purpose: the annotation would be
    ``Callable[[], Coroutine[Any, Any, bool]]``, which is the hook's own
    signature and adds nothing over reading it.
    """

    def _factory():  # type: ignore[no-untyped-def]
        return _send_disabled_email(email, notice)

    return _factory


async def _send_disabled_email(email: str, notice: _DisableNotice) -> bool:
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


async def _fail_after_crash(db: AsyncSession, *, delivery_id: str, error: BaseException) -> None:
    """Mark a row whose attempt crashed unexpectedly, in the outer transaction.

    The savepoint has already rolled back this row's writes and expired the
    objects it touched, so the row is re-read; the claim's ``FOR UPDATE`` lock
    is held by the outer transaction and is unaffected by a savepoint rollback,
    so nothing else can have touched it meanwhile.

    The hook is deliberately untouched: an unexpected exception here is ours,
    and ours must never reach a merchant's failure budget.
    """
    detail = _detail(error)
    delivery = await _load(db, delivery_id)
    delivery.status = "failed"
    delivery.attempts_count += 1
    delivery.last_error = _clip(detail, WEBHOOK_LAST_ERROR_MAX)
    log.error(
        "merchant_webhook.attempt_crashed",
        delivery_id=delivery_id,
        merchant_id=delivery.merchant_id,
        error=detail[:200],
    )


async def _load(db: AsyncSession, delivery_id: str) -> MerchantWebhookDelivery:
    """Re-read a claimed delivery row by id."""
    return (
        await db.execute(
            select(MerchantWebhookDelivery).where(MerchantWebhookDelivery.id == delivery_id)
        )
    ).scalar_one()


def _detail(exc: BaseException) -> str:
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


__all__ = ["DEFAULT_LIMIT", "drain_pending_deliveries"]
