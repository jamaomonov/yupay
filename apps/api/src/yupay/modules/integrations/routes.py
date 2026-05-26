"""Admin-only HTTP routes for supplier integrations.

CRUD over ``sku_supplier_mapping``, real-time health probes against the
supplier API, and on-demand catalog sync that populates
``supplier_catalog_cache`` for autocomplete in the mapping editor.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.admin.api import require_admin
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.schemas import (
    CatalogEntryOut,
    CatalogKind,
    CatalogListOut,
    CatalogSyncOut,
    SupplierHealthOut,
    SupplierMappingIn,
    SupplierMappingListOut,
    SupplierMappingOut,
)
from yupay.modules.inventory import service as inv_svc
from yupay.modules.users.models import User

log = get_logger("yupay.integrations.routes")

admin_router = APIRouter(
    prefix="/admin/integrations",
    tags=["admin:integrations"],
    dependencies=[Depends(require_admin)],
)

_KNOWN_SUPPLIERS = {"g2b"}


@admin_router.get(
    "/mappings",
    response_model=SupplierMappingListOut,
    summary="List supplier mappings",
)
async def list_mappings(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    supplier_slug: Annotated[str | None, Query(min_length=2, max_length=32)] = None,
    sku_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SupplierMappingListOut:
    rows = await svc.list_mappings(db, supplier_slug=supplier_slug, sku_id=sku_id, limit=limit)
    return SupplierMappingListOut(items=[SupplierMappingOut.model_validate(r) for r in rows])


@admin_router.put(
    "/mappings/{sku_id}",
    response_model=SupplierMappingOut,
    summary="Upsert the mapping for ``(sku_id, supplier_slug)``",
)
async def upsert_mapping(
    sku_id: str,
    body: SupplierMappingIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> SupplierMappingOut:
    await inv_svc.get_sku_or_404(db, sku_id)
    row = await svc.upsert_mapping(
        db,
        svc.MappingUpsert(
            sku_id=sku_id,
            supplier_slug=body.supplier_slug,
            kind=body.kind,
            external_product_id=body.external_product_id,
            external_variant_id=body.external_variant_id,
            quantity=body.quantity,
            extra=body.extra,
            is_active=body.is_active,
            updated_by=admin.id,
        ),
    )
    return SupplierMappingOut.model_validate(row)


@admin_router.delete(
    "/mappings/{sku_id}/{supplier_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Drop the mapping for ``(sku_id, supplier_slug)``",
)
async def delete_mapping(
    sku_id: str,
    supplier_slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    await svc.delete_mapping(db, sku_id=sku_id, supplier_slug=supplier_slug)


@admin_router.get(
    "/catalog",
    response_model=CatalogListOut,
    summary="Cached supplier catalog (autocomplete for mappings UI)",
)
async def list_catalog(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    supplier_slug: Annotated[str, Query(min_length=2, max_length=32)],
    kind: Annotated[CatalogKind | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CatalogListOut:
    rows = await svc.list_catalog(
        db,
        supplier_slug=supplier_slug,
        kind=kind,
        search=search,
        limit=limit,
    )
    return CatalogListOut(items=[CatalogEntryOut.model_validate(r) for r in rows])


@admin_router.post(
    "/g2b/sync-catalog",
    response_model=CatalogSyncOut,
    summary="Refresh ``supplier_catalog_cache`` from the G2B API",
)
async def sync_g2b_catalog(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> CatalogSyncOut:
    """Pulls G2B's product + game catalog into our cache.

    Best-effort: partial failures are logged but the endpoint never raises
    so the admin UI gets a definitive answer instead of a 5xx. Live
    fulfilment does NOT depend on this cache — the source of truth is
    ``sku_supplier_mapping``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return CatalogSyncOut(
            supplier="g2b",
            error="G2B_API_KEY is not configured",
        )

    client = fulfiller._client()
    vouchers = 0
    games = 0
    error: str | None = None
    try:
        products = await client.fetch_products(page=1, limit=200)
        for item in products:
            external_id = str(item.get("id") or item.get("product_id") or "").strip()
            if not external_id:
                continue
            title = str(
                item.get("title") or item.get("name") or external_id,
            )[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="g2b",
                kind="voucher",
                external_id=external_id,
                title=title,
                raw=item,
            )
            vouchers += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        error = f"voucher sync failed: {exc!s}"[:200]
        log.warning("integrations.g2b.sync.voucher_failed", error=str(exc))

    try:
        games_payload = await client.fetch_games()
        for item in games_payload:
            external_id = str(item.get("code") or item.get("id") or "").strip()
            if not external_id:
                continue
            title = str(item.get("name") or external_id)[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="g2b",
                kind="game",
                external_id=external_id,
                title=title,
                raw=item,
            )
            games += 1
    except Exception as exc:  # noqa: BLE001
        err = f"game sync failed: {exc!s}"[:200]
        error = f"{error}; {err}" if error else err
        log.warning("integrations.g2b.sync.games_failed", error=str(exc))

    await db.commit()
    return CatalogSyncOut(
        supplier="g2b",
        vouchers_synced=vouchers,
        games_synced=games,
        error=error,
    )


@admin_router.get(
    "/{supplier_slug}/health",
    response_model=SupplierHealthOut,
    summary="Connectivity probe for a supplier",
)
async def supplier_health(
    supplier_slug: str,
    _admin: Annotated[User, Depends(require_admin)],
) -> SupplierHealthOut:
    """Live probe against the supplier's status endpoint.

    For G2B we call ``GET /v1/getMe`` through the fulfiller and surface the
    balance + username back to the admin UI. The fulfiller's ``health()``
    method already swallows network errors and shapes them into
    ``{available: false, reason}`` — we just adapt to the DTO.
    """
    if supplier_slug not in _KNOWN_SUPPLIERS:
        return SupplierHealthOut(
            supplier=supplier_slug,
            available=False,
            reason="unknown supplier",
            last_checked_at=now(),
        )
    if supplier_slug == "g2b":
        from yupay.modules.fulfillment.suppliers import REGISTRY
        from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

        fulfiller = REGISTRY.get("g2b")
        if not isinstance(fulfiller, G2bFulfiller):
            return SupplierHealthOut(
                supplier="g2b",
                available=False,
                reason="g2b adapter not registered",
                last_checked_at=now(),
            )
        result = await fulfiller.health()
        balance = result.get("balance")
        return SupplierHealthOut(
            supplier="g2b",
            available=bool(result.get("available")),
            reason=result.get("reason"),
            balance=str(balance) if balance is not None else None,
            currency=None,
            username=result.get("username"),
            last_checked_at=now(),
        )
    return SupplierHealthOut(
        supplier=supplier_slug,
        available=False,
        reason="no health probe defined",
        last_checked_at=now(),
    )
