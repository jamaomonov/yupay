"""Admin-only HTTP routes for the inventory warehouse."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.inventory import service as svc
from yupay.modules.inventory.schemas import (
    BulkUploadIn,
    BulkUploadOut,
    CodeAdminListOut,
    CodeAdminOut,
    CodeState,
    SkuCountsOut,
)
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/inventory",
    tags=["admin:inventory"],
    dependencies=[Depends(require_admin)],
)


@admin_router.post(
    "/bulk-upload",
    response_model=BulkUploadOut,
    summary="Upload many voucher codes for one SKU (capped at 5000 per call)",
)
async def bulk_upload(
    body: BulkUploadIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BulkUploadOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "inventory.bulk_upload"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return BulkUploadOut.model_validate(cached.body)
    await svc.get_sku_or_404(db, body.sku_id)
    result = await svc.bulk_upload(db, sku_id=body.sku_id, codes=body.codes, uploaded_by=admin.id)
    out = BulkUploadOut(
        upload_id=result.upload_id,
        total=result.total,
        succeeded=result.succeeded,
        duplicates=result.duplicates,
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.get(
    "/sku/{sku_id}",
    response_model=SkuCountsOut,
    summary="Stock counts per state for one SKU",
)
async def sku_counts(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> SkuCountsOut:
    await svc.get_sku_or_404(db, sku_id)
    counts = await svc.counts_for_sku(db, sku_id)
    return SkuCountsOut(
        sku_id=sku_id,
        available=counts.available,
        reserved=counts.reserved,
        issued=counts.issued,
        voided=counts.voided,
    )


@admin_router.get(
    "/codes",
    response_model=CodeAdminListOut,
    summary="List codes with decrypted cleartext (admin only)",
)
async def list_codes(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    sku_id: str | None = None,
    state: CodeState | None = None,
    limit: int = 50,
) -> CodeAdminListOut:
    rows = await svc.list_codes_admin(db, sku_id=sku_id, state=state, limit=limit)
    return CodeAdminListOut(
        items=[
            CodeAdminOut(
                id=r.id,
                sku_id=r.sku_id,
                code=code,
                state=r.state,  # type: ignore[arg-type]
                order_item_id=r.order_item_id,
                reserved_at=r.reserved_at,
                issued_at=r.issued_at,
                voided_at=r.voided_at,
                expires_at=r.expires_at,
                created_at=r.created_at,
            )
            for r, code in rows
        ]
    )
