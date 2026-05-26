"""Admin-only HTTP routes for supplier integrations.

This sprint ships the foundation:

- CRUD for ``sku_supplier_mapping`` (used by future fulfilment adapters).
- A health probe for G2B that returns ``{available: false, reason: ...}``
  while the real adapter is still being built. The real probe (calling
  ``GET /v1/getMe`` on G2B and returning the balance) lands in Sprint B.

Catalog sync is also a Sprint B story.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.modules.admin.api import require_admin
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.schemas import (
    SupplierHealthOut,
    SupplierMappingIn,
    SupplierMappingListOut,
    SupplierMappingOut,
)
from yupay.modules.inventory import service as inv_svc
from yupay.modules.users.models import User

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
