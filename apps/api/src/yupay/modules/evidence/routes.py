"""Admin-only routes for the ``evidence`` module.

There is no public counterpart and there must not be one: this is the only
endpoint in the API that returns an unhashed IP address, and it exists so an
operator can answer an acquirer's document request inside the 5-day window
Payme's Общие условия п. 6.2.4 allow.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.deps import require_admin
from yupay.modules.auth.dev_login import DEV_ADMIN_ID
from yupay.modules.evidence import service as svc
from yupay.modules.evidence.schemas import EvidencePackOut
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/orders",
    tags=["admin:evidence"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "/{order_id}/evidence",
    response_model=EvidencePackOut,
    summary="Chargeback evidence pack for one order (admin)",
)
async def admin_order_evidence(
    order_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> EvidencePackOut:
    """Return the capture plus the order's full timeline.

    The read itself is recorded on the order timeline
    (``admin.evidence_viewed``) — this is the one route that hands back an
    unhashed address, so it is answerable who asked for it.
    """
    actor_id = admin.id if admin.id != DEV_ADMIN_ID else "dev_admin"
    return await svc.get_pack(db, order_id=order_id, admin_id=actor_id)


__all__ = ["admin_router"]
