"""Unit tests for the ``broadcast_media`` storage kind.

Covers the per-kind MIME allowlist and the 20 MB broadcast cap, and
guards against a regression where image kinds would start accepting
video/gif/pdf now that those MIME types exist in the global allowlist.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.modules.storage import service as svc
from yupay.modules.storage.client import get_s3_client


@pytest.fixture(autouse=True)
def _r2_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide just enough config for ``presign_upload`` to run."""
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc-test")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak-test")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk-test")
    monkeypatch.setenv("R2_BUCKET_MEDIA", "yupay-media-test")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.example.test")
    get_settings.cache_clear()


@pytest.fixture
def mock_s3() -> MagicMock:
    """Replace the cached boto3 client with a stub returning a fixed URL."""
    fake = MagicMock()
    fake.generate_presigned_url.return_value = "https://r2.example/upload?sig=fake"
    get_s3_client.cache_clear()

    import yupay.modules.storage.client as client_mod
    import yupay.modules.storage.service as service_mod

    client_mod.get_s3_client = lambda: fake  # type: ignore[assignment]
    service_mod.get_s3_client = lambda: fake  # type: ignore[assignment, attr-defined]
    return fake


def test_broadcast_media_accepts_video_mp4(mock_s3: MagicMock) -> None:
    settings = get_settings()
    result = svc.presign_upload(
        kind="broadcast_media",
        content_type="video/mp4",
        size_bytes=1024,
    )
    assert result.key.endswith(".mp4"), result.key
    assert result.key.startswith("broadcast_media/")
    assert result.max_bytes == settings.broadcast_media_max_upload_bytes
    assert result.max_bytes == 20 * 1024 * 1024


def test_broadcast_media_rejects_disallowed_mime(mock_s3: MagicMock) -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        svc.presign_upload(
            kind="broadcast_media",
            content_type="application/zip",
            size_bytes=1024,
        )


def test_brand_logo_still_rejects_video_mp4(mock_s3: MagicMock) -> None:
    """Image kinds must not start accepting video/mp4 just because the
    global MIME allowlist now includes it for broadcasts."""
    with pytest.raises(ValidationError, match="not allowed"):
        svc.presign_upload(
            kind="brand_logo",
            content_type="video/mp4",
            size_bytes=1024,
        )


def test_broadcast_media_rejects_oversize(mock_s3: MagicMock) -> None:
    settings = get_settings()
    too_big = settings.broadcast_media_max_upload_bytes + 1
    with pytest.raises(ValidationError, match="exceeds"):
        svc.presign_upload(
            kind="broadcast_media",
            content_type="video/mp4",
            size_bytes=too_big,
        )
    # Sanity: this must be well above the (unrelated) 5 MB image cap too,
    # otherwise the test would pass for the wrong reason.
    assert too_big > settings.media_max_upload_bytes
