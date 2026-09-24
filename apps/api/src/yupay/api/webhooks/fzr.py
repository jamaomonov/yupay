"""FazerCards order-status webhook receiver.

Unlike G2B's callback, this one is **signed**: FazerCards sends
``X-Webhook-Signature: sha256=<hex>``, an HMAC-SHA256 of the raw body under a
secret shown in their reseller panel. §9 of AGENTS.md requires that signature
to be verified *before* the body is parsed, which is why this handler reads
``await request.body()`` and does not touch ``request.json()`` until the
comparison has passed.

**The body is never trusted even after that.** A valid signature proves who
sent the request, not what is true: the handler takes only the order id from
it and hands off to ``process_webhook_update``, which asks the adapter's own
``check_status`` for the authoritative state. That is the same rule the G2B
receiver follows and the same one the polling path follows.

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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
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
    """Verify, identify the task, and let the adapter decide what is true."""
    raw = await request.body()
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

    updated = await fulfillment_svc.process_webhook_update(db, task_id=task.id)
    log.info("fzr.webhook.processed", task_id=updated.id, new_status=updated.status)
    return {"status": "processed", "task_status": updated.status}


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
