"""The webhook outbox's **consumer** — claim a row, sign it, send it.

Spec §10, M3a Task 4. :mod:`.webhooks` fills the outbox in the transaction that
causes each event; this module drains it from ``apps/worker``, in exactly the
shape ``fulfillment.service.drain_pending_tasks`` established (ADR-0064): claim
with ``FOR UPDATE SKIP LOCKED``, one ``SAVEPOINT`` per row, never commit —
the worker owns the transaction and commits after every batch.

Two neighbours own the halves that are not the send. :mod:`.webhook_retry` is
the retry table, pure and with no idea a database exists.
:mod:`.webhook_outcome` is everything that happens *after* the answer comes
back (or fails to): the row's log, the hook's health, the auto-disable and its
one email. The split is AGENTS §6 — together they were 600 lines — but the
seam is the concern, not the line count.

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

## What is never logged

The secret, the signature, and the body. The secret is decrypted at send time
and lives in one local; the signature authorises the delivery; the body is the
merchant's own event data. The delivery **URL** is not logged either — a
webhook path can carry a token — though it is stored on the row, which is the
merchant's own record of their own endpoint.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select

from yupay.core import crypto
from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.core.outbound import post_json
from yupay.core.outbound_errors import OutboundError
from yupay.modules.merchants import signing, webhook_retry
from yupay.modules.merchants import webhook_outcome as outcome
from yupay.modules.merchants.models import MerchantWebhook, MerchantWebhookDelivery
from yupay.modules.merchants.webhooks import EVENT_TYPES

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.merchants.webhook_delivery")

#: How many rows one claim takes. Matches ``drain_pending_tasks``' default:
#: the worker drains until a batch comes back empty, so this bounds how long
#: one transaction (and therefore one merchant's hook-row lock) is held, not
#: how much work a wake does.
DEFAULT_LIMIT: Final = 20


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
        notice: outcome.DisableNotice | None = None
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
            await outcome.fail_after_crash(db, delivery_id=delivery_id, error=exc)
        if notice is not None:
            await outcome.announce_disable(db, notice)
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


async def _attempt(db: AsyncSession, *, delivery_id: str) -> outcome.DisableNotice | None:
    """Send one delivery and write the outcome onto its row.

    Args:
        db: Session, inside this row's savepoint.
        delivery_id: The claimed row.

    Returns:
        A notice when this attempt tripped the auto-disable, else ``None``.
    """
    delivery = await outcome.load_delivery(db, delivery_id)
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
        return await outcome.record(
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
        return await outcome.record(
            db,
            delivery=delivery,
            decision=webhook_retry.decide_failure(exc, attempts=attempts),
            at=at,
            response=None,
            error=outcome.detail(exc),
        )
    decision = webhook_retry.decide_response(
        status_code=response.status_code,
        retry_after=response.retry_after,
        attempts=attempts,
        now=at,
    )
    return await outcome.record(
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


__all__ = ["DEFAULT_LIMIT", "drain_pending_deliveries"]
