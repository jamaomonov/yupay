"""Admin route for the unified audit feed."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.audit import service as svc
from yupay.modules.audit.schemas import AuditEventOut, AuditListOut, AuditSource
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/audit",
    tags=["admin:audit"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "",
    response_model=AuditListOut,
    summary="Unified activity feed across orders / payments / fulfilment / wallet",
)
async def admin_audit_feed(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    sources: Annotated[
        list[AuditSource] | None,
        Query(
            description=(
                "Optional list of source tables to include. Omitted = all five."
            ),
        ),
    ] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
) -> AuditListOut:
    capped = max(1, min(limit, 500))
    rows = await svc.list_audit_events(
        db,
        sources=sources,
        since=since,
        until=until,
        actor=actor,
        target_id=target_id,
        limit=capped,
    )
    return AuditListOut(
        items=[
            AuditEventOut(
                id=e.id,
                ts=e.ts,
                source=e.source,  # type: ignore[arg-type]
                kind=e.kind,
                actor=e.actor,
                target_id=e.target_id,
                target_kind=e.target_kind,
                payload=e.payload,
            )
            for e in rows
        ]
    )
