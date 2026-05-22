"""Routes owned directly by the ``admin`` module.

Historically the module only exposed the ``require_admin`` dependency. Sprint-0 of the
task-oriented admin refactor (ADR-0017) introduces the first cross-entity endpoint here:
``GET /admin/search`` for the cmd+k palette.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin import service as svc
from yupay.modules.admin.deps import require_admin
from yupay.modules.admin.schemas import CustomerOverviewOut, SearchOut
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "/search",
    response_model=SearchOut,
    summary="Cross-entity search (users / orders / payments / skus)",
)
async def admin_search(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    q: Annotated[str, Query(min_length=2, max_length=64, description="Search query")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> SearchOut:
    """Return up to ``limit`` matches per source for the given query."""
    return await svc.search(db, q=q, limit=limit)


@admin_router.get(
    "/customers/{user_id}/overview",
    response_model=CustomerOverviewOut,
    summary="Aggregated customer-360 view (orders, payments, wallet, risk flags)",
)
async def admin_customer_overview(
    user_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=50, description="Rows per section")] = 10,
) -> CustomerOverviewOut:
    """Single aggregate read for the /customers/{user_id} page in the admin SPA."""
    return await svc.get_customer_overview(db, user_id=user_id, limit=limit)


__all__ = ["admin_router"]
