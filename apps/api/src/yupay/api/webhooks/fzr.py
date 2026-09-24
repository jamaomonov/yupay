"""FazerCards order-status webhook receiver.

Unlike G2B's callback, this one is **signed**: FazerCards sends
``X-Webhook-Signature: sha256=<hex>``, an HMAC-SHA256 of the raw body under a
secret shown in their reseller panel. §9 of AGENTS.md requires that signature
to be verified *before* the body is parsed, which is why this handler reads
``await request.body()`` and does not touch ``request.json()`` until the
comparison has passed.

**The body is never trusted even after that.** A valid signature proves who
sent the request, not what is true. So the handler takes only the order id
from it, marks that task due for a status check, and answers. The check
itself — the adapter's own ``check_status`` — runs on the reconcile sweep,
which is the authority either way.

**It deliberately does not reconcile inline.** ``check_status`` is a live HTTP
call with a 20-second timeout, and a request handler holds its pool connection
for its whole lifetime; the API pool is 10 + 10, so twenty concurrent
deliveries would exhaust it and take the API down. That shape already produced
a ``QueuePool limit of size 10 overflow 10 reached`` here on 2026-09-23, and
FazerCards asks for the opposite in their own documentation: "Respond quickly
(200 within seconds); do heavy work asynchronously." The cost is at most one
sweep tick — ten seconds — against a backoff that would otherwise have been
sixty for any order older than two minutes, which is exactly the order a
customer is still waiting on.

Three facts from their retry policy shape the responses below:

* non-2xx and a 10-second timeout both count as a failure;
* a failure is retried three times — after 1, 5 and 30 minutes;
* **after 50 consecutive failures they disable the webhook** and it has to be
  re-enabled by hand in their panel.

So anything we cannot act on still answers ``200``. A 404 for an order we have
never heard of would be honest and would, fifty orders later, silently turn
the feature off. The only refusal here is a bad signature.

Mounted at ``/api/v1/webhooks/fzr``. Polling still runs: this makes delivery
land in seconds instead of up to a minute, and it is not the only path, so a
missed event costs latency rather than an order.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment import service as fulfillment_svc
from yupay.modules.fulfillment.models import FulfillmentTask

router = APIRouter(prefix="/webhooks/fzr", tags=["webhooks:fzr"])
log = get_logger("yupay.webhooks.fzr")

#: The events that can change a task's state. ``order.created`` tells us
#: nothing we do not already know — we created it — and the manual-service
#: chat events belong to a product we do not sell here.
_ACTIONABLE = frozenset({"order.status_changed"})

#: Their prefix on the signature header value.
_PREFIX = "sha256="

#: Biggest body we will read. Their payload is a few hundred bytes; this is
#: three orders of magnitude of headroom and still bounds what an unsigned
#: caller can make us hold in memory. Checked on ``Content-Length`` **before**
#: the body is read, because reading it is the cost being avoided.
MAX_BODY_BYTES = 64 * 1024

#: How stale a delivery may be. Their retry ladder is 1, 5 and 30 minutes and
#: a retry carries the original ``timestamp``, so anything under ~36 minutes
#: would reject their own legitimate third attempt. An hour is the smallest
#: window that cannot do that.
#:
#: This is defence in depth, not the main control: since the handler stopped
#: reconciling inline there is no upstream call to amplify, and marking a task
#: due twice is the same as marking it once. It bounds how long a captured
#: delivery stays replayable, nothing more.
MAX_AGE_SECONDS = 3600


def _too_old(body: dict[str, Any]) -> bool:
    """Whether this delivery's own timestamp is outside :data:`MAX_AGE_SECONDS`.

    An unreadable or absent timestamp is **not** treated as stale: we would be
    refusing a real delivery over a field we only use for defence in depth,
    and their auto-disable counter is what would pay for it.
    """
    raw = str(body.get("timestamp") or "").strip()
    if not raw:
        return False
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return abs((now() - at).total_seconds()) > MAX_AGE_SECONDS


def _signature_ok(raw: bytes, header: str, secret: str) -> bool:
    """Whether this body was signed with our secret.

    Fails closed on an unset secret: an unconfigured receiver that accepted
    everything would be worse than one that accepts nothing, because it would
    look like it was working.
    """
    if not secret or not header:
        return False
    expected = _PREFIX + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    # ``header`` is untrusted wire input; ``compare_digest`` rejects non-ASCII
    # ``str`` operands with TypeError, so compare bytes and fail closed.
    return hmac.compare_digest(header.encode("utf-8", "replace"), expected.encode())


@router.post(
    "",
    summary="FazerCards order-status callback",
    status_code=status.HTTP_200_OK,
)
async def receive_fzr_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    signature: Annotated[str, Header(alias="X-Webhook-Signature")] = "",
) -> dict[str, Any]:
    """Verify, identify the task, mark it due, answer. Nothing slow here."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        # Refused before reading a byte of it. 413 rather than 401: it is not
        # a forgery claim, and their retry of something this large will not
        # get smaller.
        log.warning("fzr.webhook.body_too_large", declared=int(declared))
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        # A chunked body declares no length, so the cap is enforced twice.
        log.warning("fzr.webhook.body_too_large", declared=len(raw))
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    if not _signature_ok(raw, signature, get_settings().fzr_webhook_secret):
        # 401, not 404: their own documentation uses it, and unlike the order
        # cases below a bad signature is not something retrying will fix, so
        # the auto-disable counter is the right pressure.
        log.warning("fzr.webhook.bad_signature", bytes=len(raw))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001 -- signed, but not necessarily JSON
        body = {}

    if _too_old(body):
        log.warning("fzr.webhook.stale")
        return {"status": "ignored", "reason": "stale"}

    event = str(body.get("event") or "").strip()
    if event not in _ACTIONABLE:
        # Acknowledged, deliberately: see the module docstring on their
        # auto-disable counter.
        return {"status": "ignored", "event": event}

    data = body.get("data")
    order_id = str((data or {}).get("order_id") or "").strip() if isinstance(data, dict) else ""
    if not order_id:
        # ``event_name``, not ``event``: our structured logger takes the
        # event name as its own first argument, so the obvious kwarg
        # collides with it and raises where it is meant to explain.
        log.warning("fzr.webhook.missing_order_id", event_name=event)
        return {"status": "ignored", "reason": "missing order_id"}

    task = await _task_for(db, order_id)
    if task is None:
        log.warning("fzr.webhook.unknown_order", fzr_order_id=order_id)
        return {"status": "unknown_order"}

    hurried = await fulfillment_svc.mark_due_now(db, task_id=task.id)
    await db.commit()
    log.info("fzr.webhook.queued", task_id=task.id, hurried=hurried)
    # ``hurried`` false means the task already reached a terminal state, which
    # is a normal race with the sweep and not something to retry.
    return {"status": "queued" if hurried else "already_final"}


async def _task_for(db: AsyncSession, order_id: str) -> FulfillmentTask | None:
    """The task this order belongs to, newest first.

    Two places hold their id and both have to be read. The column is the
    ordinary case; ``extra_metadata.fzr_order_id`` is where an **adopted**
    order's id lands — the reconciler merges that map onto the task but never
    moves the id into the column. ``check_status`` already reads both, and a
    webhook that read only the column would ignore exactly the orders whose
    create response was lost, which are the ones most worth hearing about.
    """
    return (
        await db.execute(
            select(FulfillmentTask)
            .where(
                FulfillmentTask.supplier == "fzr",
                or_(
                    FulfillmentTask.external_order_id == order_id,
                    FulfillmentTask.extra_metadata["fzr_order_id"].astext == order_id,
                ),
            )
            .order_by(FulfillmentTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
