"""FoxReload order webhook receiver (ADR-0107).

Signed: ``X-Webhook-Signature: t=<unix>,v1=<hex>``, an HMAC-SHA256 under the
webhook's own secret over ``"{t}." + raw body``. §9 of AGENTS.md: the signature
is verified on the raw bytes before the body is parsed, and a timestamp more
than :data:`TOLERANCE_SECONDS` from our clock is refused, as their docs ask.

**The body is not trusted even then.** The handler takes only the order id
(``data.id``), marks that task due, and answers; the adapter's own
``check_status`` on the ``foxreload_reconcile`` sweep (10 s) reads the order and
is the authority — the same split as the fzr receiver, for the same pool reason.

Events: ``order.completed`` and ``order.action_required`` act; anything else is
acknowledged with 200. They retry a non-2xx 5 times (30 s … 30 min), so a
delivery we cannot act on still answers 200; only a bad signature is refused.
A failed or refunded order sends no event — the sweep notices those.

Mounted at ``/api/v1/webhooks/foxreload``.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment import service as fulfillment_svc
from yupay.modules.fulfillment.models import FulfillmentTask

router = APIRouter(prefix="/webhooks/foxreload", tags=["webhooks:foxreload"])
log = get_logger("yupay.webhooks.foxreload")

_ACTIONABLE = frozenset({"order.completed", "order.action_required"})

#: Their order body with codes is a few KB; bounded before it is read.
MAX_BODY_BYTES = 256 * 1024

#: Their own figure: reject timestamps more than five minutes off.
TOLERANCE_SECONDS = 300


def _signature_ok(raw: bytes, header: str, secret: str, *, at: float | None = None) -> bool:
    """Whether ``raw`` was signed with ``secret`` within the tolerance.

    Fails closed on an unset secret, a missing or malformed header, a stale or
    future timestamp, and a non-ASCII signature.
    """
    if not secret or not header:
        return False
    try:
        parts = dict(part.strip().split("=", 1) for part in header.split(","))
        stamp = int(parts["t"])
        given = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((time.time() if at is None else at) - stamp) > TOLERANCE_SECONDS:
        return False
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given.encode("utf-8", "replace"), expected.encode())


@router.post("", summary="FoxReload order callback", status_code=status.HTTP_200_OK)
async def receive_foxreload_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    signature: Annotated[str, Header(alias="X-Webhook-Signature")] = "",
) -> dict[str, Any]:
    """Verify, find the task, mark it due, answer. Nothing slow here."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    if not _signature_ok(raw, signature, get_settings().foxreload_webhook_secret):
        log.warning("foxreload.webhook.bad_signature", bytes=len(raw))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001 -- signed, but not necessarily JSON
        body = {}
    event = str(body.get("type") or "").strip() if isinstance(body, dict) else ""
    if event not in _ACTIONABLE:
        return {"status": "ignored", "event": event}

    data = body.get("data")
    order_id = str(data.get("id") or "").strip() if isinstance(data, dict) else ""
    if not order_id:
        log.warning("foxreload.webhook.missing_order_id", event_name=event)
        return {"status": "ignored", "reason": "missing order id"}

    task = (
        await db.execute(
            select(FulfillmentTask)
            .where(
                FulfillmentTask.supplier == "foxreload",
                FulfillmentTask.external_order_id == order_id,
            )
            .order_by(FulfillmentTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if task is None:
        log.warning("foxreload.webhook.unknown_order", foxreload_order_id=order_id)
        return {"status": "unknown_order"}

    hurried = await fulfillment_svc.mark_due_now(db, task_id=task.id)
    await db.commit()
    log.info("foxreload.webhook.queued", task_id=task.id, hurried=hurried, event_name=event)
    return {"status": "queued" if hurried else "already_final"}
