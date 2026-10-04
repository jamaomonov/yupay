"""Telegram Business updates for @depositlistenerbot -> P2P intake (spec §5.4).

Authenticity first: Telegram echoes the ``secret_token`` we gave ``setWebhook``
in ``X-Telegram-Bot-Api-Secret-Token``. It is compared before a byte of the body
is read, and an unset secret refuses everything — an unconfigured receiver
that accepted all would look like it worked.

Idempotency-Key does not apply: Telegram is the caller, and the journal's
``(business_connection_id, message_id)`` unique key makes a retry a no-op.
"""

from __future__ import annotations

import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.modules.notifications.alerts import send_admin_alert
from yupay.modules.p2p.intake import ingest_update

router = APIRouter(prefix="/webhooks/telegram", tags=["webhooks:telegram"])
MAX_BODY_BYTES = 64 * 1024


@router.post(
    "/p2p", status_code=status.HTTP_200_OK, summary="HUMO notifications via Telegram Business"
)
async def receive_p2p_update(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    secret: Annotated[str, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = "",
) -> dict[str, Any]:
    """Verify the secret header, journal the update, credit a matching reservation."""
    expected = get_settings().p2p_webhook_secret
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        update = json.loads(raw)
    except ValueError:
        return {"ok": True}  # Telegram's own body; a retry would be the same bytes.
    if not isinstance(update, dict):
        return {"ok": True}
    result = await ingest_update(db, update, received_at=now())
    # Commit before alerting: the dependency would commit only after the handler
    # returns, and an alert must never describe a state that is not yet durable.
    await db.commit()
    for kind, text in result.alerts:
        await send_admin_alert(text, kind=kind)
    return {"ok": True}
