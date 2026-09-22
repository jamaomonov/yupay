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
from yupay.core.logging import get_logger
from yupay.modules.admin.api import require_admin
from yupay.modules.integrations.schemas import CostSyncResult
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

log = get_logger("yupay.sourcing.routes")

admin_router = APIRouter(
    prefix="/admin/sourcing",
    tags=["admin:sourcing"],
    dependencies=[Depends(require_admin)],
)


def _rule_out(
    row: SkuSourcingRule, sku_code: str, *, cost_sync: CostSyncResult | None = None
) -> SourcingRuleOut:
    """Build ``SourcingRuleOut`` from the ORM row plus a separately resolved
    ``sku_code`` (no ORM relationship to ``Sku`` to pull it from — see
    ``svc.sku_codes_for``).

    ``cost_sync`` is only ever populated by a write — a listing has not
    re-priced anything and says so by leaving it ``None``."""
    return SourcingRuleOut.model_validate(
        {**row.__dict__, "sku_code": sku_code, "cost_sync": cost_sync}
    )


async def _reprice_after_switch(db: AsyncSession, sku_id: str) -> CostSyncResult:
    """Re-price a SKU onto the supplier it was just routed to.

    Best-effort by design: the operator's decision was the route, and it is
    already written. A supplier that will not answer, a catalogue that has
    not been synced, a bug in the lookup — none of those should turn a
    successful switch into a 5xx that leaves the operator unsure whether the
    route moved. The failure travels back in ``reason`` instead.

    ``allow_price_drop=False``, unlike the on-save mapping refresh: choosing
    where we buy is not choosing what we charge. Cheaper supplier, same shelf
    price and a wider margin; dearer supplier, price re-derived from the new
    cost, because the alternative is selling below cost until the next tick.
    """
    from yupay.modules.integrations.cost_refresh import refresh_routed_cost

    try:
        outcome = await refresh_routed_cost(db, sku_id=sku_id, allow_price_drop=False)
    except Exception as exc:  # noqa: BLE001 -- the route change must still stand
        log.warning("sourcing.reprice_failed", sku_id=sku_id, error=str(exc)[:200])
        return CostSyncResult(
            updated=False, reason=f"не удалось обновить себестоимость: {exc}"[:200]
        )
    return CostSyncResult(
        updated=outcome.updated,
        old_cost=str(outcome.old_cost) if outcome.old_cost is not None else None,
        new_cost=str(outcome.new_cost) if outcome.new_cost is not None else None,
        source=outcome.source,
        reason=outcome.reason,
        old_price=str(outcome.old_price) if outcome.old_price is not None else None,
        new_price=str(outcome.new_price) if outcome.new_price is not None else None,
        price_drop_blocked=outcome.price_drop_blocked,
    )


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
    cost_sync = await _reprice_after_switch(db, sku_id)
    sku_codes = await svc.sku_codes_for(db, [sku_id])
    out = _rule_out(rule, sku_codes.get(sku_id, sku_id), cost_sync=cost_sync)
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
    # Only the SKUs whose rule actually landed: a failed write routed nothing,
    # so there is nothing to re-price and a cost move there would be a lie.
    for item in items:
        if item.ok:
            item.cost_sync = await _reprice_after_switch(db, item.sku_id)
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
