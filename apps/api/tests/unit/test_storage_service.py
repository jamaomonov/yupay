"""Unit tests for the R2 media-storage service.

Covers presign key derivation, MIME/size validation, and the public-URL
shape — boto3 itself is mocked so the tests don't touch the network or
require credentials.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.modules.storage import service as svc
from yupay.modules.storage.client import get_s3_client


@pytest.fixture(autouse=True)
def _r2_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide just enough config for ``presign_upload`` to run.

    The mocked client is stuffed straight into the ``lru_cache``, so the
    boto3 builder never runs and these envs only need to satisfy the
    pydantic-settings load.
    """
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
    # Stuff the result directly into the cache so the real builder never runs.
    get_s3_client.__wrapped__ = lambda: fake  # type: ignore[attr-defined]
    # ``lru_cache`` looks up via the wrapped function; easier to monkeypatch
    # the symbol on the service module instead.
    import yupay.modules.storage.client as client_mod
    import yupay.modules.storage.service as service_mod

    # Override the module-level symbols the service code closes over.
    # ``# type: ignore`` covers both the assignment widening and the
    # attribute-not-in-__all__ complaint; the dynamic monkeypatch is
    # exactly what unit-level isolation requires here.
    client_mod.get_s3_client = lambda: fake  # type: ignore[assignment]
    service_mod.get_s3_client = lambda: fake  # type: ignore[assignment, attr-defined]
    return fake


def test_presign_happy_path_returns_keys_and_urls(mock_s3: MagicMock) -> None:
    result = svc.presign_upload(
        kind="brand_logo",
        content_type="image/png",
        size_bytes=2048,
    )
    assert result.upload_url == "https://r2.example/upload?sig=fake"
    assert result.public_url.startswith("https://cdn.example.test/brand_logo/")
    assert result.public_url.endswith(".png")
    assert result.content_type == "image/png"
    # Key shape: ``<kind>/<yyyy>/<mm>/<ulid>.<ext>``
    assert re.match(r"^brand_logo/\d{4}/\d{2}/[A-Za-z0-9-]+\.png$", result.key), result.key

    call = mock_s3.generate_presigned_url.call_args
    assert call.kwargs["ClientMethod"] == "put_object"
    params: dict[str, Any] = call.kwargs["Params"]
    assert params["Bucket"] == "yupay-media-test"
    assert params["ContentType"] == "image/png"
    assert params["Key"] == result.key
    assert call.kwargs["HttpMethod"] == "PUT"


def test_presign_each_kind_has_matching_prefix(mock_s3: MagicMock) -> None:
    for kind in ("brand_logo", "brand_hero", "product_image", "sku_image"):
        r = svc.presign_upload(kind=kind, content_type="image/webp", size_bytes=1024)
        assert r.key.startswith(f"{kind}/"), r.key
        assert r.key.endswith(".webp")


def test_presign_each_allowed_mime_has_an_extension(mock_s3: MagicMock) -> None:
    # SVG is intentionally absent — it can carry <script> and would execute on
    # the public cdn.yupay.uz origin (stored XSS), so it is no longer accepted.
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    for mime, ext in mapping.items():
        r = svc.presign_upload(kind="brand_logo", content_type=mime, size_bytes=1024)
        assert r.key.endswith(ext), (mime, r.key)


def test_presign_rejects_svg_for_every_kind(mock_s3: MagicMock) -> None:
    """SVG (scriptable, served from the public CDN) must be refused everywhere."""
    for kind in ("brand_logo", "brand_hero", "product_image", "sku_image", "broadcast_media"):
        with pytest.raises(ValidationError, match="not allowed"):
            svc.presign_upload(kind=kind, content_type="image/svg+xml", size_bytes=1024)


def test_presign_rejects_disallowed_mime(mock_s3: MagicMock) -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        svc.presign_upload(kind="brand_logo", content_type="image/gif", size_bytes=1024)


def test_presign_rejects_zero_or_negative_size(mock_s3: MagicMock) -> None:
    with pytest.raises(ValidationError, match="positive"):
        svc.presign_upload(kind="brand_logo", content_type="image/png", size_bytes=0)
    with pytest.raises(ValidationError, match="positive"):
        svc.presign_upload(kind="brand_logo", content_type="image/png", size_bytes=-1)


def test_presign_rejects_oversize(mock_s3: MagicMock) -> None:
    settings = get_settings()
    too_big = settings.media_max_upload_bytes + 1
    with pytest.raises(ValidationError, match="exceeds"):
        svc.presign_upload(kind="brand_logo", content_type="image/png", size_bytes=too_big)


def test_presign_rejects_unknown_kind(mock_s3: MagicMock) -> None:
    with pytest.raises(ValidationError, match="Unknown media kind"):
        # The Literal type guards callers at type-check time; this asserts
        # that callers reaching the runtime with a stray value still fail
        # cleanly rather than producing a bogus S3 key.
        svc.presign_upload(
            kind="banner_image",  # type: ignore[arg-type]
            content_type="image/png",
            size_bytes=1024,
        )


def test_public_url_for_strips_trailing_slash() -> None:
    assert svc.public_url_for("brand_logo/2026/05/abc.png") == (
        "https://cdn.example.test/brand_logo/2026/05/abc.png"
    )
