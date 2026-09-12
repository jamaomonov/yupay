"""Presigned upload + key/URL derivation for R2-hosted media.

A presign call returns a short-lived PUT URL the browser can use to
upload directly to R2, plus the public ``cdn.yupay.uz`` URL the caller
should persist in the relevant DB column once the upload returns 200.

Key layout::

    <kind>/<yyyy>/<mm>/<ulid>.<ext>

* ``<kind>`` mirrors ``MediaKind`` — buys grep-ability when an admin
  reports "the brand_logo for X is broken".
* ``yyyy/mm`` keeps any single listing call cheap and lets us run
  retention rules per month if we ever need them.
* ``<ulid>`` is a fresh ULID (sortable, collision-free) — never derive
  the key from the source filename, that's a path-traversal vector and
  it also leaks PII when admins drag in screenshots named
  ``Sasha.jpeg``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, get_args

from botocore.exceptions import BotoCoreError, ClientError

from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id
from yupay.modules.storage.client import get_s3_client

MediaKind = Literal[
    "brand_logo",
    "brand_hero",
    "product_image",
    "sku_image",
    "broadcast_media",
    "blog_image",
]
MEDIA_KINDS: tuple[MediaKind, ...] = get_args(MediaKind)

_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "application/pdf": "pdf",
}

# Raster only. SVG is deliberately excluded: it can carry <script>/<foreignObject>
# and would execute in the public ``cdn.yupay.uz`` origin when opened directly
# (stored XSS). A brand logo / product image never needs a vector format.
_IMAGE_MIME: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/webp"})

# Per-kind MIME allowlist. Broadcasts attach video/GIF/document in
# addition to a plain photo; the raster image-only kinds must NOT widen
# just because those types exist in ``settings.media_allowed_mime`` now
# — an admin picking a brand logo should still be refused an .mp4.
_KIND_ALLOWED_MIME: dict[str, set[str]] = {
    "brand_logo": set(_IMAGE_MIME),
    "brand_hero": set(_IMAGE_MIME),
    "product_image": set(_IMAGE_MIME),
    "sku_image": set(_IMAGE_MIME),
    "blog_image": set(_IMAGE_MIME),
    "broadcast_media": set(_IMAGE_MIME) | {"image/gif", "video/mp4", "application/pdf"},
}


@dataclass(frozen=True, slots=True)
class PresignResult:
    """Everything the admin SPA needs to do the upload + persist the URL."""

    upload_url: str
    public_url: str
    key: str
    content_type: str
    expires_in: int
    max_bytes: int


def _ext_for(content_type: str) -> str:
    """Map a Content-Type to a stable filesystem extension.

    Raises:
        ValidationError: when the MIME type is not in
            ``settings.media_allowed_mime``.
    """
    settings = get_settings()
    if content_type not in settings.media_allowed_mime:
        raise ValidationError(
            f"Content-Type {content_type!r} is not allowed for media uploads.",
        )
    # ``_MIME_TO_EXT`` is the source of truth — the settings list controls
    # *which* are allowed, but we still need a fixed extension for each.
    ext = _MIME_TO_EXT.get(content_type)
    if ext is None:
        # New MIME added to the allowlist without a corresponding extension.
        raise ValidationError(
            f"No file extension mapping for Content-Type {content_type!r}.",
        )
    return ext


def _build_key(kind: MediaKind, content_type: str) -> str:
    now = datetime.now(UTC)
    return f"{kind}/{now:%Y}/{now:%m}/{new_id()}.{_ext_for(content_type)}"


def public_url_for(key: str) -> str:
    """Return the publicly-reachable URL for a stored object key."""
    base = get_settings().r2_public_base_url.rstrip("/")
    return f"{base}/{key}"


def presign_upload(
    *,
    kind: MediaKind,
    content_type: str,
    size_bytes: int,
) -> PresignResult:
    """Mint a presigned PUT URL for one direct-from-browser upload.

    Args:
        kind: Which surface the image will be used on. Determines the key
            prefix, the per-kind MIME allowlist (``_KIND_ALLOWED_MIME``),
            and is reflected back to the caller as an audit trail.
        content_type: The browser's reported MIME. Pinned into the
            presigned URL — if the actual PUT sends a different
            Content-Type, R2 rejects the request. Validated against the
            allowlist for ``kind``, not the global
            ``settings.media_allowed_mime``, so image kinds can't upload
            a video just because broadcasts widened the global list.
        size_bytes: Caller-provided size hint. Validated up front against
            ``settings.broadcast_media_max_upload_bytes`` (20 MB) for
            ``kind="broadcast_media"`` or ``settings.media_max_upload_bytes``
            (5 MB) for every other kind, so the SPA can fail loudly before
            opening an oversized file. R2 itself caps the PUT via the
            ``Content-Length`` header the browser includes.

    Returns:
        :class:`PresignResult`. ``upload_url`` is single-use — issue a
        new one for each retry.

    Raises:
        ValidationError: invalid ``kind``, disallowed MIME, or oversize.
        RuntimeError: R2 client could not sign (typically missing creds).
    """
    if kind not in MEDIA_KINDS:
        raise ValidationError(f"Unknown media kind {kind!r}.")

    if content_type not in _KIND_ALLOWED_MIME[kind]:
        raise ValidationError(
            f"Content-Type {content_type!r} is not allowed for kind {kind!r}.",
        )

    settings = get_settings()
    if size_bytes <= 0:
        raise ValidationError("Upload size must be positive.")
    cap = (
        settings.broadcast_media_max_upload_bytes
        if kind == "broadcast_media"
        else settings.media_max_upload_bytes
    )
    if size_bytes > cap:
        raise ValidationError(f"Upload exceeds the {cap} byte limit.")

    key = _build_key(kind, content_type)
    s3 = get_s3_client()
    try:
        # ``put_object`` so the browser uses a vanilla PUT; multipart
        # presign would add complexity for files this small (≤20 MB).
        upload_url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": settings.r2_bucket_media,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.r2_presign_ttl_seconds,
            HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError) as exc:
        # boto3 will raise locally for malformed config; treat as a 500
        # to the caller via FastAPI's default handler.
        raise RuntimeError(f"Could not generate presigned URL: {exc}") from exc

    return PresignResult(
        upload_url=upload_url,
        public_url=public_url_for(key),
        key=key,
        content_type=content_type,
        expires_in=settings.r2_presign_ttl_seconds,
        max_bytes=cap,
    )


__all__ = [
    "MEDIA_KINDS",
    "MediaKind",
    "PresignResult",
    "presign_upload",
    "public_url_for",
]
