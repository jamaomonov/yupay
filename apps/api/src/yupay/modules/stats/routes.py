"""Admin stats routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.stats import service as svc
from yupay.modules.stats.schemas import DashboardOut
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/stats",
    tags=["admin:stats"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "/dashboard",
    response_model=DashboardOut,
    summary="Aggregate KPI payload for the admin Dashboard page",
)
async def admin_dashboard(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    window_hours: int = 24,
) -> DashboardOut:
    return await svc.build_dashboard(db, window_hours=max(1, min(window_hours, 24 * 30)))
