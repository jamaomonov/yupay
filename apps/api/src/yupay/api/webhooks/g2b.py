"""G2B (G2Bulk) webhook receiver.

G2B doesn't sign callbacks — the only authentication on the inbound path
is the secret token in the URL. We additionally re-verify the order's
status via the supplier API before mutating any task state (see ADR-0019).

Mounted under ``/api/v1/webhooks/g2b/{secret}``. A wrong secret returns
404 — we don't reveal that the route exists.
"""

from __future__ import annotations

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
    if not expected or secret != expected:
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

    updated = await fulfillment_svc.process_webhook_update(db, task_id=task.id)
    log.info(
        "g2b.webhook.processed",
        task_id=updated.id,
        new_status=updated.status,
    )
    return {"status": "processed", "task_status": updated.status}
