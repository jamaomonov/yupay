"""Tests for the Payme (Paycom) acquirer config fields.

Mirrors the Octo acquirer's config: env var names map 1:1 onto ``Settings``
field names (``PAYME_MERCHANT_ID`` -> ``payme_merchant_id``, etc.),
case-insensitive, via pydantic-settings.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from yupay.core import config as cfg


@pytest.fixture
def _clear_settings_cache() -> Iterator[None]:
    """Clear the cached ``Settings`` before and after each test.

    ``get_settings`` is process-lifetime cached via ``lru_cache``. Without
    clearing on both sides, whichever test in the suite calls it first
    freezes the result for every test that follows — including ones outside
    this module. Mirrors the session fixture in ``tests/conftest.py``.
    """
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_payme_login_defaults_to_paycom(_clear_settings_cache: None) -> None:
    assert cfg.get_settings().payme_login == "Paycom"


def test_payme_checkout_url_defaults_to_production(_clear_settings_cache: None) -> None:
    assert cfg.get_settings().payme_checkout_url == "https://checkout.paycom.uz"


def test_payme_test_key_is_read_from_env(
    monkeypatch: pytest.MonkeyPatch,
    _clear_settings_cache: None,
) -> None:
    monkeypatch.setenv("PAYME_TEST_KEY", "sandbox-test-key-123")
    assert cfg.get_settings().payme_test_key == "sandbox-test-key-123"
