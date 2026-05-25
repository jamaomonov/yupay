"""boto3 client for Cloudflare R2.

R2's S3 API only implements path-style signatures; we therefore lock
``addressing_style="path"`` and use signature v4. The client is built
lazily and cached for the process lifetime — boto3 clients are
thread-safe and the credentials don't rotate at runtime.

Calls in this codebase only use the **presign** capability (a
fully-local crypto operation, no network). For that the sync boto3
client is enough; introducing ``aioboto3`` would only buy complexity
without a corresponding latency win.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config

from yupay.core.config import get_settings


@lru_cache(maxsize=1)
def get_s3_client() -> Any:  # boto3 ships no type stubs; mypy_boto3_s3 is optional.
    """Return a cached boto3 S3 client pointed at Cloudflare R2.

    Raises:
        RuntimeError: when the R2 credentials/account are not configured
            in :class:`Settings`. Surfaces early instead of failing on
            the first upload attempt.
    """
    settings = get_settings()
    if not settings.r2_account_id or not settings.r2_access_key_id:
        raise RuntimeError(
            "R2 credentials are not configured "
            "(set R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY).",
        )
    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        # R2 only honours v4 + path-style — anything else returns
        # ``NotImplemented`` for presigned URLs.
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            # The presign step is local crypto, but boto3 still validates
            # the region; ``auto`` matches what R2 documents.
            region_name="auto",
        ),
    )


__all__ = ["get_s3_client"]
