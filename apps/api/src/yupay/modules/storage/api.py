"""Public surface of the ``storage`` module.

Other modules import only what this file exposes — never reach into
``service`` / ``routes`` / ``client`` directly. Keeps the public surface
intentional and the dependency direction clean (see ADR on module
boundaries).
"""

from yupay.modules.storage.routes import admin_router
from yupay.modules.storage.schemas import PresignUploadIn, PresignUploadOut
from yupay.modules.storage.service import (
    MEDIA_KINDS,
    MediaKind,
    PresignResult,
    is_own_media_url,
    presign_upload,
    public_url_for,
)

__all__ = [
    "MEDIA_KINDS",
    "MediaKind",
    "PresignResult",
    "PresignUploadIn",
    "PresignUploadOut",
    "admin_router",
    "is_own_media_url",
    "presign_upload",
    "public_url_for",
]
