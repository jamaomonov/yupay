"""Unit tests for the ``field_help_image`` storage kind and ``is_own_media_url``.

``field_help_image`` holds the screenshots a form field's ``help_images``
list points at (see ``catalog.schemas.HelpImage``) — same raster-only MIME
rules and 5 MB cap as the other image kinds, landing under its own key
prefix rather than mixing with brand logos and blog covers.

``is_own_media_url`` is the single predicate for "this URL points at our
own R2 media bucket" — the guard that keeps a product's help images from
becoming an arbitrary remote-image embed. ``catalog.schemas.HelpImage``
reuses it via ``storage.api`` rather than re-deriving the prefix.
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
    """Provide just enough config for ``presign_upload``/``is_own_media_url`` to run."""
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


# ---------- field_help_image kind ----------


def test_field_help_image_accepts_webp(mock_s3: MagicMock) -> None:
    result = svc.presign_upload(kind="field_help_image", content_type="image/webp", size_bytes=1024)
    assert result.key.startswith("field_help_image/"), result.key
    assert result.key.endswith(".webp")
    assert result.max_bytes == get_settings().media_max_upload_bytes


def test_field_help_image_rejects_svg(mock_s3: MagicMock) -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        svc.presign_upload(kind="field_help_image", content_type="image/svg+xml", size_bytes=1024)


def test_field_help_image_rejects_video(mock_s3: MagicMock) -> None:
    """Must not widen just because broadcast_media accepts video."""
    with pytest.raises(ValidationError, match="not allowed"):
        svc.presign_upload(kind="field_help_image", content_type="video/mp4", size_bytes=1024)


def test_field_help_image_rejects_oversize(mock_s3: MagicMock) -> None:
    settings = get_settings()
    too_big = settings.media_max_upload_bytes + 1
    with pytest.raises(ValidationError, match="exceeds"):
        svc.presign_upload(kind="field_help_image", content_type="image/png", size_bytes=too_big)


# ---------- is_own_media_url ----------


def test_is_own_media_url_accepts_a_url_under_the_public_base() -> None:
    url = svc.public_url_for("field_help_image/2026/09/abc123.png")
    assert svc.is_own_media_url(url) is True


def test_is_own_media_url_rejects_another_host() -> None:
    assert svc.is_own_media_url("https://res.cloudinary.com/demo/image/upload/x.png") is False


def test_is_own_media_url_rejects_a_lookalike_host() -> None:
    """A host that merely starts with our prefix as a substring must not
    pass — only an exact scheme+netloc match counts."""
    assert svc.is_own_media_url("https://cdn.example.test.evil.com/x.png") is False


def test_is_own_media_url_rejects_wrong_scheme() -> None:
    assert svc.is_own_media_url("http://cdn.example.test/x.png") is False


def test_is_own_media_url_rejects_malformed_url() -> None:
    assert svc.is_own_media_url("not-a-url") is False
