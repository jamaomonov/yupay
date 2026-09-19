"""Unit tests for ``FormField.help_images`` (``HelpImage``).

Pure Pydantic — no DB, no HTTP. Covers the two server-side limits on a
form field's "where do I find this?" screenshot walkthrough: at most six
images, and every url must point at our own R2 media bucket
(``storage.service.is_own_media_url``). The round trip through the actual
``POST /admin/catalog/products`` endpoint — where an operator actually
reaches this limit — is covered in
``tests/integration/test_admin_catalog_routes.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from yupay.core.config import get_settings
from yupay.modules.catalog.schemas import FormField, HelpImage


@pytest.fixture(autouse=True)
def _own_media_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``r2_public_base_url`` so the "own bucket" checks are deterministic."""
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.example.test")
    get_settings.cache_clear()


def _field(**overrides: Any) -> FormField:
    """Build a valid ``FormField`` via ``model_validate`` (raw-dict input,
    same as an admin write payload), with ``overrides`` merged in."""
    payload: dict[str, Any] = {
        "key": "player_id",
        "label": {"ru": "ID игрока"},
        "type": "text",
        "required": True,
        **overrides,
    }
    return FormField.model_validate(payload)


def _own_url(n: int) -> str:
    return f"https://cdn.example.test/field_help_image/2026/09/{n}.png"


def test_form_field_accepts_help_images_up_to_six() -> None:
    images = [{"url": _own_url(i)} for i in range(6)]
    field = _field(help_images=images)
    assert field.help_images is not None
    assert len(field.help_images) == 6


def test_form_field_rejects_a_seventh_help_image() -> None:
    images = [{"url": _own_url(i)} for i in range(7)]
    with pytest.raises(ValidationError, match="at most 6"):
        _field(help_images=images)


def test_form_field_accepts_none_help_images() -> None:
    field = _field()
    assert field.help_images is None


def test_form_field_accepts_empty_help_images_list() -> None:
    field = _field(help_images=[])
    assert field.help_images == []


def test_help_image_rejects_url_on_another_host() -> None:
    """A plausible third-party CDN — not our bucket — must be refused."""
    with pytest.raises(ValidationError, match="own media bucket"):
        _field(help_images=[{"url": "https://res.cloudinary.com/demo/image/upload/x.png"}])


def test_help_image_preserves_order_and_caption() -> None:
    images = [
        {"url": _own_url(0), "caption": {"ru": "Открой профиль"}},
        {"url": _own_url(1), "caption": {"ru": "ID под ником"}},
    ]
    field = _field(help_images=images)
    assert field.help_images is not None
    assert [img.url for img in field.help_images] == [_own_url(0), _own_url(1)]
    assert field.help_images[0].caption == {"ru": "Открой профиль"}


def test_help_image_caption_optional() -> None:
    field = _field(help_images=[{"url": _own_url(0)}])
    assert field.help_images is not None
    assert field.help_images[0].caption is None


def test_help_image_rejects_unknown_key() -> None:
    """``HelpImage`` forbids extras, same as every other nested form-field shape."""
    with pytest.raises(ValidationError):
        _field(help_images=[{"url": _own_url(0), "bogus": "x"}])


def test_form_field_now_accepts_help_images_instead_of_rejecting_as_extra() -> None:
    """Before this field existed, ``FormField``'s ``extra=\"forbid\"`` rejected
    ``help_images`` outright — this is what makes it a recognised field."""
    field = _field(help_images=[{"url": _own_url(0)}])
    assert field.help_images is not None
    assert isinstance(field.help_images[0], HelpImage)
