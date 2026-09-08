"""Admin HTTP routes for the B2B knobs that live on catalog rows.

``catalog_b2b_router`` under ``/admin/catalog`` — per-SKU markup/visibility,
bulk markup, brand visibility. It is mounted beside ``merchants.admin_routes``'
``admin_router`` and split out of that file when it passed AGENTS.md §6's
split-before-500 line; the two share the replay helpers in
:mod:`yupay.modules.merchants.route_replay`.

The rules the sibling router documents hold here unchanged: business logic is
imported through the ``merchants.api`` facade only (routers parse and
dispatch, AGENTS.md §6), every write accepts ``Idempotency-Key`` and replays
through the generic ``(scope, key)`` store, and ``api/v1`` imports this router
from here rather than from the facade — a router re-exported from the facade
would close a cycle back through the v1 route stack.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.idempotency import normalize_idempotency_key
from yupay.modules.admin.api import require_admin
from yupay.modules.merchants import api as merchants
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed
from yupay.modules.merchants.schemas import (
    BrandB2bOut,
    BrandB2bPatchIn,
    BulkMarkupIn,
    BulkMarkupOut,
    SkuB2bOut,
    SkuB2bPatchIn,
)

catalog_b2b_router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin:catalog-b2b"],
    dependencies=[Depends(require_admin)],
)


@catalog_b2b_router.patch(
    "/skus/{sku_id}/b2b",
    response_model=SkuB2bOut,
    summary="Set a SKU's B2B markup and/or visibility",
)
async def patch_sku_b2b(
    sku_id: str,
    body: SkuB2bPatchIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> SkuB2bOut:
    """Absent fields stay untouched; no pricing math here (AGENTS.md §6)."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.sku_b2b:{sku_id}"
    cached = await replayed(db, scope=scope, key=key, model=SkuB2bOut)
    if cached is not None:
        return cached
    sku = await merchants.set_sku_b2b(
        db, sku_id=sku_id, markup_pct=body.markup_pct, visible_b2b=body.visible_b2b
    )
    out = SkuB2bOut.model_validate(sku)
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


@catalog_b2b_router.post(
    "/b2b/bulk-markup",
    response_model=BulkMarkupOut,
    summary="Set the B2B markup for a whole brand or category in one action",
)
async def bulk_markup(
    body: BulkMarkupIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> BulkMarkupOut:
    """One UPDATE over the brand's (or category's) SKUs; returns the affected count."""
    key = normalize_idempotency_key(idempotency_key)
    # Discriminated by target KIND, not just its name: a brand slug and a
    # category name can be the same string ("steam"), and a bare name would
    # let one reused key replay the brand update for the category one and
    # silently never apply it.
    scope = (
        f"merchants.bulk_markup:brand:{body.brand_slug}"
        if body.brand_slug is not None
        else f"merchants.bulk_markup:category:{body.category}"
    )
    cached = await replayed(db, scope=scope, key=key, model=BulkMarkupOut)
    if cached is not None:
        return cached
    affected = await merchants.bulk_set_markup(
        db,
        markup_pct=body.markup_pct,
        brand_slug=body.brand_slug,
        category_slug=body.category,
    )
    out = BulkMarkupOut(affected=affected)
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


@catalog_b2b_router.patch(
    "/brands/{brand_id}/b2b",
    response_model=BrandB2bOut,
    summary="Show or hide a whole brand in the merchant catalog",
)
async def patch_brand_b2b(
    brand_id: str,
    body: BrandB2bPatchIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> BrandB2bOut:
    """Effective B2B visibility is ``brand.visible_b2b AND sku.visible_b2b``."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.brand_b2b:{brand_id}"
    cached = await replayed(db, scope=scope, key=key, model=BrandB2bOut)
    if cached is not None:
        return cached
    brand = await merchants.set_brand_b2b(db, brand_id=brand_id, visible_b2b=body.visible_b2b)
    out = BrandB2bOut.model_validate(brand)
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["catalog_b2b_router"]
