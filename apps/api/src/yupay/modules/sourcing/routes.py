"""Admin-only HTTP routes for sourcing rules."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.inventory import service as inv_svc
from yupay.modules.sourcing import service as svc
from yupay.modules.sourcing.schemas import (
    SourcingDecisionOut,
    SourcingRuleIn,
    SourcingRuleListOut,
    SourcingRuleOut,
)
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/sourcing",
    tags=["admin:sourcing"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "/rules", response_model=SourcingRuleListOut, summary="List all explicit rules"
)
async def list_rules(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    limit: int = 200,
) -> SourcingRuleListOut:
    rules = await svc.list_rules(db, limit=limit)
    return SourcingRuleListOut(
        items=[SourcingRuleOut.model_validate(r) for r in rules]
    )


@admin_router.get(
    "/rules/{sku_id}",
    response_model=SourcingDecisionOut,
    summary="What sourcing decision applies to this SKU right now",
)
async def get_decision(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> SourcingDecisionOut:
    await inv_svc.get_sku_or_404(db, sku_id)
    decision = await svc.resolve_for_sku(db, sku_id)
    return SourcingDecisionOut(
        primary=decision.primary,
        fallback=decision.fallback,
        strict=decision.strict,
        rule_present=decision.rule_present,
    )


@admin_router.put(
    "/rules/{sku_id}",
    response_model=SourcingRuleOut,
    summary="Upsert the rule for a SKU",
)
async def upsert_rule(
    sku_id: str,
    body: SourcingRuleIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> SourcingRuleOut:
    await inv_svc.get_sku_or_404(db, sku_id)
    rule = await svc.set_rule(
        db,
        sku_id=sku_id,
        mode=body.mode,
        supplier_slug=body.supplier_slug,
        admin_id=admin.id,
    )
    return SourcingRuleOut.model_validate(rule)


@admin_router.delete(
    "/rules/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Drop the rule — SKU falls back to 'auto'",
)
async def delete_rule(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    await svc.delete_rule(db, sku_id)
