"""Admin-only HTTP routes for direct-to-R2 media uploads."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from yupay.modules.admin.api import require_admin
from yupay.modules.storage import service as svc
from yupay.modules.storage.schemas import PresignUploadIn, PresignUploadOut
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/media",
    tags=["admin:media"],
    dependencies=[Depends(require_admin)],
)


@admin_router.post(
    "/presign-upload",
    response_model=PresignUploadOut,
    summary="Mint a presigned PUT URL for a single direct-to-R2 image upload",
)
async def presign_upload(
    body: PresignUploadIn,
    # ``admin`` is unused in the handler body but the dependency must be
    # resolved per-request to enforce auth; assigning it gives ruff
    # something to point at if someone tries to delete the line.
    admin: Annotated[User, Depends(require_admin)],  # noqa: ARG001
) -> PresignUploadOut:
    result = svc.presign_upload(
        kind=body.kind,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
    )
    return PresignUploadOut(
        upload_url=result.upload_url,
        public_url=result.public_url,
        key=result.key,
        content_type=result.content_type,
        expires_in=result.expires_in,
        max_bytes=result.max_bytes,
    )


__all__ = ["admin_router"]
