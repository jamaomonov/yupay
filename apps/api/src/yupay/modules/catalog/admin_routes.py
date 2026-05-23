"""Admin (write) HTTP routes for the catalog module.

Mounted under ``/api/v1/admin/catalog/*``. Every endpoint depends on
:func:`require_admin` from the ``admin`` module — non-admin tokens get 403.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.catalog import admin_service as svc
from yupay.modules.catalog.admin_schemas import (
    AdminBrandOut,
    AdminCategoryOut,
    AdminProductOut,
    AdminSkuOut,
    BrandCreate,
    BrandUpdate,
    BulkUzsPriceOut,
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
    SkuCreate,
    SkuUpdate,
)
from yupay.modules.fx.factory import build_default_service
from yupay.modules.users.models import User

router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin:catalog"],
    dependencies=[Depends(require_admin)],
)


# ---------- categories ----------


@router.get("/categories", response_model=list[AdminCategoryOut])
async def list_categories(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[AdminCategoryOut]:
    """All categories (incl. inactive) for the admin tree."""
    return [AdminCategoryOut.model_validate(c) for c in await svc.list_all_categories(db)]


@router.post("/categories", response_model=AdminCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryCreate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminCategoryOut:
    row = await svc.create_category(db, body)
    return AdminCategoryOut.model_validate(row)


@router.patch("/categories/{category_id}", response_model=AdminCategoryOut)
async def update_category(
    category_id: str,
    body: CategoryUpdate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminCategoryOut:
    row = await svc.update_category(db, category_id, body)
    return AdminCategoryOut.model_validate(row)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    await svc.delete_category(db, category_id)


# ---------- brands ----------


@router.get("/brands", response_model=list[AdminBrandOut])
async def list_brands(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[AdminBrandOut]:
    return [AdminBrandOut.model_validate(b) for b in await svc.list_all_brands(db)]


@router.post("/brands", response_model=AdminBrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(
    body: BrandCreate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminBrandOut:
    row = await svc.create_brand(db, body)
    return AdminBrandOut.model_validate(row)


@router.patch("/brands/{brand_id}", response_model=AdminBrandOut)
async def update_brand(
    brand_id: str,
    body: BrandUpdate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminBrandOut:
    row = await svc.update_brand(db, brand_id, body)
    return AdminBrandOut.model_validate(row)


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    brand_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    await svc.delete_brand(db, brand_id)


# ---------- products ----------


@router.get("/products", response_model=list[AdminProductOut])
async def list_products(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    brand_id: str | None = None,
) -> list[AdminProductOut]:
    return [
        AdminProductOut.model_validate(p)
        for p in await svc.list_all_products(db, brand_id=brand_id)
    ]


@router.post("/products", response_model=AdminProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminProductOut:
    row = await svc.create_product(db, body)
    return AdminProductOut.model_validate(row)


@router.patch("/products/{product_id}", response_model=AdminProductOut)
async def update_product(
    product_id: str,
    body: ProductUpdate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminProductOut:
    row = await svc.update_product(db, product_id, body)
    return AdminProductOut.model_validate(row)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    await svc.delete_product(db, product_id)


# ---------- SKUs ----------


@router.get("/skus", response_model=list[AdminSkuOut])
async def list_skus(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    product_id: str | None = None,
) -> list[AdminSkuOut]:
    return [
        AdminSkuOut.model_validate(s)
        for s in await svc.list_all_skus(db, product_id=product_id)
    ]


@router.post("/skus", response_model=AdminSkuOut, status_code=status.HTTP_201_CREATED)
async def create_sku(
    body: SkuCreate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminSkuOut:
    row = await svc.create_sku(db, body)
    return AdminSkuOut.model_validate(row)


@router.patch("/skus/{sku_id}", response_model=AdminSkuOut)
async def update_sku(
    sku_id: str,
    body: SkuUpdate,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminSkuOut:
    row = await svc.update_sku(db, sku_id, body)
    return AdminSkuOut.model_validate(row)


@router.delete("/skus/{sku_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sku(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    await svc.delete_sku(db, sku_id)


@router.post("/skus/bulk-set-uzs-prices", response_model=BulkUzsPriceOut)
async def bulk_set_uzs_prices(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> BulkUzsPriceOut:
    """Recompute UZS SkuPrice overrides for every active SKU.

    Uses the same FX service that orders use at checkout (so the rate
    here matches the rate customers will see today). SKUs whose
    ``cost_usdt`` is null are skipped — they remain at whatever UZS
    override they had, or fall back to live FX in catalog reads.
    """
    fx = build_default_service()
    result = await svc.bulk_set_uzs_prices(db, fx_service=fx)
    return BulkUzsPriceOut(
        rate=result["rate"],
        fx_snapshot_id=result["fx_snapshot_id"],
        updated_total=result["updated_total"],
        skipped_without_cost=result["skipped_without_cost"],
    )
