"""Admin stats routes."""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.redis import get_redis
from yupay.modules.admin.api import require_admin
from yupay.modules.stats import service as svc
from yupay.modules.stats.schemas import (
    AnalyticsRange,
    BusinessAnalyticsOut,
    DashboardOut,
    OpsAnalyticsOut,
)
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


_ANALYTICS_TTL = 300


async def _cached[AnalyticsT: BaseModel](
    key: str,
    model: type[AnalyticsT],
    builder: Callable[[], Awaitable[AnalyticsT]],
) -> AnalyticsT:
    """Return a cached analytics payload or compute, cache (TTL 300s), and return.

    Best-effort: Redis errors fall back to a live computation so the dashboard
    never 500s on a cache hiccup.

    Args:
        key: Redis cache key (embeds the validated range only).
        model: Pydantic model used to rebuild the cached JSON.
        builder: Zero-arg async callable that computes the payload on a miss.

    Returns:
        The cached or freshly-computed analytics payload.
    """
    r = get_redis()
    with contextlib.suppress(Exception):  # cache is best-effort
        raw = await r.get(key)
        if raw is not None:
            return model.model_validate_json(raw)
    payload = await builder()
    with contextlib.suppress(Exception):  # cache is best-effort
        await r.set(key, payload.model_dump_json(), ex=_ANALYTICS_TTL)
    return payload


@admin_router.get(
    "/analytics/business",
    response_model=BusinessAnalyticsOut,
    summary="Business analytics (revenue, margin, funnel, mix, customers)",
)
async def analytics_business(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    range_: Annotated[AnalyticsRange, Query(alias="range")] = AnalyticsRange.D30,
) -> BusinessAnalyticsOut:
    return await _cached(
        f"stats:analytics:business:{range_.value}",
        BusinessAnalyticsOut,
        lambda: svc.build_business_analytics(db, r=range_),
    )


@admin_router.get(
    "/analytics/ops",
    response_model=OpsAnalyticsOut,
    summary="Operational analytics (payments, fulfilment, inventory)",
)
async def analytics_ops(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    range_: Annotated[AnalyticsRange, Query(alias="range")] = AnalyticsRange.D30,
) -> OpsAnalyticsOut:
    return await _cached(
        f"stats:analytics:ops:{range_.value}",
        OpsAnalyticsOut,
        lambda: svc.build_ops_analytics(db, r=range_),
    )
