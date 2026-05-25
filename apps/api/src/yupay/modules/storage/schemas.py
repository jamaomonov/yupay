"""Pydantic IO schemas for the storage module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from yupay.modules.storage.service import MEDIA_KINDS, MediaKind


class PresignUploadIn(BaseModel):
    """Request body for ``POST /admin/media/presign-upload``."""

    kind: MediaKind = Field(
        ...,
        description=f"One of {', '.join(MEDIA_KINDS)}.",
    )
    content_type: str = Field(..., examples=["image/png", "image/webp"])
    # Mandatory so the SPA fails before opening huge files; R2 enforces
    # the cap server-side via Content-Length, this is the cheap UX gate.
    size_bytes: int = Field(..., gt=0)


class PresignUploadOut(BaseModel):
    """Response body for ``POST /admin/media/presign-upload``.

    Workflow on the admin side::

        const { upload_url, public_url } = await api.presignUpload(...);
        await fetch(upload_url, {
          method: "PUT",
          headers: { "Content-Type": file.type },
          body: file,
        });
        // Persist ``public_url`` into the relevant form field.
    """

    upload_url: str = Field(
        ...,
        description="Single-use presigned PUT URL. Expires in ``expires_in`` seconds.",
    )
    public_url: str = Field(
        ...,
        description="Public read URL (cdn.yupay.uz). Store this in the DB column.",
    )
    key: str
    content_type: str
    expires_in: int
    max_bytes: int


__all__ = ["PresignUploadIn", "PresignUploadOut"]
