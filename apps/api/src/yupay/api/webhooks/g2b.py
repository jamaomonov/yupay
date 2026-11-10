"""G2B (G2Bulk) webhook receiver.

G2B doesn't sign callbacks — the only authentication on the inbound path
is the secret token in the URL. We additionally re-verify the order's
status via the supplier API before mutating any task state (see ADR-0019).

Mounted under ``/api/v1/webhooks/g2b/{secret}``. A wrong secret returns
404 — we don't reveal that the route exists. The handler only marks the task
due; the ``g2b_reconcile`` sweep does the supplier call (see the handler).
"""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment import service as fulfillment_svc
from yupay.modules.fulfillment.models import FulfillmentTask

router = APIRouter(prefix="/webhooks/g2b", tags=["webhooks:g2b"])
log = get_logger("yupay.webhooks.g2b")


@router.post(
    "/{secret}",
    summary="G2B order-status callback",
    status_code=status.HTTP_200_OK,
)
async def receive_g2b_webhook(
    secret: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    expected = get_settings().g2b_webhook_secret
    # Note: the secret lives in the URL path segment (G2B doesn't support a
    # header-based alternative today), which can leak via proxy/access logs —
    # moving it to a header would need a supplier-side config change and is
    # out of scope here. At least keep the comparison itself constant-time.
    try:
        secret_ok = bool(expected) and hmac.compare_digest(secret, expected)
    except TypeError:
        # ``secret`` is untrusted wire input and may contain non-ASCII
        # characters, which ``hmac.compare_digest`` rejects on ``str``
        # operands — fail closed instead of propagating.
        secret_ok = False
    if not secret_ok:
        # 404 — don't acknowledge existence to the wrong sender.
        raise HTTPException(status_code=404)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001 -- body might be empty / non-JSON
        body = {}

    g2b_order_id = str(body.get("order_id") or "").strip()
    if not g2b_order_id:
        log.warning("g2b.webhook.missing_order_id")
        return {"status": "ignored", "reason": "missing order_id"}

    # Find our task by ``external_order_id`` — multiple tasks could in
    # theory share the same upstream id (admin retry), but the latest one
    # is what we should reconcile.
    task = (
        await db.execute(
            select(FulfillmentTask)
            .where(
                FulfillmentTask.supplier == "g2b",
                FulfillmentTask.external_order_id == g2b_order_id,
            )
            .order_by(FulfillmentTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if task is None:
        log.warning(
            "g2b.webhook.unknown_order",
            g2b_order_id=g2b_order_id,
        )
        # 200 to make G2B stop retrying — we genuinely have nothing for them.
        return {"status": "unknown_order"}

    # Queue, never reconcile here (audit 2026-11-10). ``process_webhook_update``
    # calls G2B with a 20 s timeout while this request holds a pool
    # connection, so a burst of deliveries — or anyone holding the path secret,
    # which access logs used to record — could drain the API pool, the
    # 2026-09-23 outage fzr's receiver was fixed for. ``g2b_reconcile`` checks
    # every in-flight G2B task each minute and re-reads the status from G2B,
    # so a delivery lands within a minute and the body is still never trusted.
    hurried = await fulfillment_svc.mark_due_now(db, task_id=task.id)
    await db.commit()
    log.info("g2b.webhook.queued", task_id=task.id, hurried=hurried)
    return {"status": "queued" if hurried else "already_final"}
