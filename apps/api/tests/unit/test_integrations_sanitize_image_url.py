"""Unit test for the G2B import's SSRF image-URL handling.

Pure function — no DB. ``_sanitize_image_url`` is what makes ``import_game``
(``yupay.modules.integrations.service``) "least disruptive": an admin-typed
brand/product image URL that fails the SSRF host check
(``yupay.modules.catalog.image_url_safety``) aborts that whole write via a
Pydantic ``ValidationError``, but a bad URL coming off the G2B import should
just drop the image, not sink the entire game import. See
``test_g2b_import.py`` for the end-to-end (DB-backed) import behaviour.
"""

from __future__ import annotations

from yupay.modules.integrations.service import _sanitize_image_url


def test_sanitize_passes_through_a_public_https_url() -> None:
    url = "https://cdn.example.com/box-art.png"
    assert _sanitize_image_url(url) == url


def test_sanitize_blanks_an_ssrf_target_instead_of_raising() -> None:
    assert _sanitize_image_url("https://169.254.169.254/latest/meta-data/") is None


def test_sanitize_blanks_localhost() -> None:
    assert _sanitize_image_url("https://localhost/x") is None


def test_sanitize_passes_through_none() -> None:
    assert _sanitize_image_url(None) is None
