"""Admin-only HTTP routes for sourcing rules."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.inventory import service as inv_svc
from yupay.modules.sourcing import brand_overview as brand_overview_svc
from yupay.modules.sourcing import bulk_rules as bulk_rules_svc
from yupay.modules.sourcing import service as svc
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.sourcing.schemas import (
    SourcingBrandOverviewOut,
    SourcingBulkRuleIn,
    SourcingBulkRuleOut,
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


def _rule_out(row: SkuSourcingRule, sku_code: str) -> SourcingRuleOut:
    """Build ``SourcingRuleOut`` from the ORM row plus a separately resolved
    ``sku_code`` (no ORM relationship to ``Sku`` to pull it from — see
    ``svc.sku_codes_for``)."""
    return SourcingRuleOut.model_validate({**row.__dict__, "sku_code": sku_code})


@admin_router.get("/rules", response_model=SourcingRuleListOut, summary="List all explicit rules")
async def list_rules(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    limit: int = 200,
) -> SourcingRuleListOut:
    rules = await svc.list_rules(db, limit=limit)
    sku_codes = await svc.sku_codes_for(db, (r.sku_id for r in rules))
    return SourcingRuleListOut(
        items=[_rule_out(r, sku_codes.get(r.sku_id, r.sku_id)) for r in rules]
    )


@admin_router.get(
    "/brands/{brand_slug}",
    response_model=SourcingBrandOverviewOut,
    summary="Sourcing overview for every active SKU of a brand",
)
async def brand_overview(
    brand_slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> SourcingBrandOverviewOut:
    return await brand_overview_svc.get_brand_overview(db, brand_slug)


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
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SourcingRuleOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "sourcing.upsert_rule"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            # Tolerate replay bodies cached before ``sku_code`` was added (the
            # deploy window): fall back to the sku_id, matching the fresh path's
            # fallback for a missing code, so a same-key retry never 500s.
            data = {**(cached.body or {})}
            data.setdefault("sku_code", data.get("sku_id", ""))
            return SourcingRuleOut.model_validate(data)
    await inv_svc.get_sku_or_404(db, sku_id)
    rule = await svc.set_rule(
        db,
        sku_id=sku_id,
        mode=body.mode,
        supplier_slug=body.supplier_slug,
        admin_id=admin.id,
    )
    sku_codes = await svc.sku_codes_for(db, [sku_id])
    out = _rule_out(rule, sku_codes.get(sku_id, sku_id))
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.put(
    "/rules:bulk",
    response_model=SourcingBulkRuleOut,
    summary="Switch many SKUs to one sourcing decision in a single request",
)
async def bulk_upsert_rules(
    body: SourcingBulkRuleIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SourcingBulkRuleOut:
    """Apply one sourcing decision to up to :data:`MAX_BULK_SKU_IDS` SKUs at once.

    ``body.sku_ids`` is capped at :data:`MAX_BULK_SKU_IDS` (100) — a longer
    list is a whole-request 422, not 100 individual failures; a caller with
    more SKUs than that (e.g. a brand larger than 100) must chunk the
    request itself. Each listed SKU is its own unit of work: one SKU with no
    active mapping for a forced supplier, or a concurrent write racing it,
    fails by name in that item's ``{sku_id, ok: false, error}`` without
    aborting the rest — partial success, not all-or-nothing. Same
    ``Idempotency-Key`` contract as every other write here (§9 AGENTS.md):
    one key per attempt, not per selection — see the module ``README.md``.

    Args:
        body: ``{sku_ids, mode, supplier_slug}`` — one decision for every
            listed SKU.
        db: Request-scoped session (``core.db.get_session``).
        admin: The authenticated admin caller; recorded as each written
            rule's ``updated_by``.
        idempotency_key: Optional ``Idempotency-Key`` header; a repeat with
            the same key replays the first response verbatim.

    Returns:
        One result per input SKU, in input order.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = "sourcing.bulk_upsert_rules"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return SourcingBulkRuleOut.model_validate(cached.body)
    items = await bulk_rules_svc.bulk_set_rules(
        db,
        sku_ids=body.sku_ids,
        mode=body.mode,
        supplier_slug=body.supplier_slug,
        admin_id=admin.id,
    )
    out = SourcingBulkRuleOut(items=items)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.delete(
    "/rules/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Drop the rule — SKU falls back to 'auto'",
)
async def delete_rule(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> None:
    key = normalize_idempotency_key(idempotency_key)
    scope = "sourcing.delete_rule"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return
    await svc.delete_rule(db, sku_id)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=None)
    return
