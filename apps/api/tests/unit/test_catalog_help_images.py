"""Unit tests for ``FormField.help_images`` (``HelpImage``).

Pure Pydantic — no DB, no HTTP. Covers the two server-side limits on a
form field's "where do I find this?" screenshot walkthrough: at most six
images, and every url must point at our own R2 media bucket
(``storage.service.is_own_media_url``). The round trip through the actual
``POST /admin/catalog/products`` endpoint — where an operator actually
reaches this limit — is covered in
``tests/integration/test_admin_catalog_routes.py``.

Also covers the write-vs-read split on the same-bucket check: strict (raise)
by default — which is what every write path gets, since FastAPI parses
``ProductCreate``/``ProductUpdate`` request bodies with no validation
context — versus lenient (drop the offending image, keep the rest) when a
caller opts in via ``context=HELP_IMAGES_READ_CONTEXT``, which is what the
storefront and admin *read* paths do. See
``tests/integration/test_catalog_routes.py`` and
``test_admin_catalog_routes.py`` for the same split exercised through a real
stored row and the HTTP layer.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from yupay.core.config import get_settings
from yupay.modules.catalog.schemas import HELP_IMAGES_READ_CONTEXT, FormField, HelpImage


@pytest.fixture(autouse=True)
def _own_media_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``r2_public_base_url`` so the "own bucket" checks are deterministic."""
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.example.test")
    get_settings.cache_clear()


def _field(**overrides: Any) -> FormField:
    """Build a valid ``FormField`` via ``model_validate`` (raw-dict input,
    same as an admin write payload), with ``overrides`` merged in. No
    validation context — the strict, write-path default."""
    payload: dict[str, Any] = {
        "key": "player_id",
        "label": {"ru": "ID игрока"},
        "type": "text",
        "required": True,
        **overrides,
    }
    return FormField.model_validate(payload)


def _field_on_read(**overrides: Any) -> FormField:
    """Same as ``_field``, but validated the way the storefront and admin
    *read* paths do: with ``context=HELP_IMAGES_READ_CONTEXT``, so a
    non-conforming ``help_images`` entry is dropped instead of raising."""
    payload: dict[str, Any] = {
        "key": "player_id",
        "label": {"ru": "ID игрока"},
        "type": "text",
        "required": True,
        **overrides,
    }
    return FormField.model_validate(payload, context=HELP_IMAGES_READ_CONTEXT)


def _own_url(n: int) -> str:
    return f"https://cdn.example.test/field_help_image/2026/09/{n}.png"


_FOREIGN_URL = "https://res.cloudinary.com/demo/image/upload/x.png"


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
    # Deliberately descending (not ascending, like _own_url's own numbering)
    # so a stray `.sort()` on the list would actually be caught here.
    images = [
        {"url": _own_url(1), "caption": {"ru": "Открой профиль"}},
        {"url": _own_url(0), "caption": {"ru": "ID под ником"}},
    ]
    field = _field(help_images=images)
    assert field.help_images is not None
    assert [img.url for img in field.help_images] == [_own_url(1), _own_url(0)]
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


# ---------- write vs. read: HELP_IMAGES_READ_CONTEXT ----------


def test_help_image_on_read_drops_a_foreign_url_instead_of_raising() -> None:
    """The lenient read path a config cutover (or a seed bypassing the
    model) needs: the same payload that raises in ``_field`` (see
    ``test_help_image_rejects_url_on_another_host``) instead loses just the
    one bad picture."""
    field = _field_on_read(
        help_images=[{"url": _own_url(0)}, {"url": _FOREIGN_URL}, {"url": _own_url(1)}]
    )
    assert field.help_images is not None
    assert [img.url for img in field.help_images] == [_own_url(0), _own_url(1)]


def test_help_image_on_read_preserves_order_of_kept_images() -> None:
    """Dropping a bad entry must not disturb the order of the survivors —
    the order *is* the walkthrough."""
    field = _field_on_read(
        help_images=[
            {"url": _own_url(2)},
            {"url": _FOREIGN_URL},
            {"url": _own_url(0)},
            {"url": _own_url(1)},
        ]
    )
    assert field.help_images is not None
    assert [img.url for img in field.help_images] == [_own_url(2), _own_url(0), _own_url(1)]


def test_help_image_on_read_drops_every_image_if_all_are_foreign() -> None:
    """An all-bad row degrades to no walkthrough, not a 500."""
    field = _field_on_read(help_images=[{"url": _FOREIGN_URL}])
    assert field.help_images == []


def test_help_image_write_path_still_rejects_without_context() -> None:
    """Sanity check that the read-path leniency is genuinely opt-in: the
    exact same payload validated the way a write body is (no context) still
    422s. Guards against ``_field_on_read``'s context becoming the default."""
    with pytest.raises(ValidationError, match="own media bucket"):
        _field(help_images=[{"url": _FOREIGN_URL}])


def test_a_read_truncates_past_the_cap_instead_of_failing_the_page() -> None:
    """A seed can write a seventh image; the storefront must still render.

    The cap does not depend on mutable config, so only a model-bypassing write
    can exceed it — and `scripts/seed/` writing `required_fields` with raw
    `jsonb_set` is how this column is populated in practice. Letting it raise
    on read costs the whole product page, which is never the right answer to a
    data problem.
    """
    seven = [{"url": _own_url(n), "caption": None} for n in range(7)]

    field = _field_on_read(help_images=seven)

    assert field.help_images is not None
    assert len(field.help_images) == 6
    # The survivors are the first six in order, not an arbitrary subset.
    assert [i.url for i in field.help_images] == [_own_url(n) for n in range(6)]


def test_a_write_still_refuses_a_seventh_image() -> None:
    """The lenient read must not have softened the write."""
    seven = [{"url": _own_url(n), "caption": None} for n in range(7)]

    with pytest.raises(ValidationError, match="at most"):
        _field(help_images=seven)
