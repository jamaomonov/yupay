"""Tests for the Uzum Bank Merchant API acquirer config fields.

Mirrors the Payme acquirer's config: env var names map 1:1 onto ``Settings``
field names (``UZUM_SERVICE_ID`` -> ``uzum_service_id``, etc.),
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


def test_uzum_open_service_url_defaults_to_production(_clear_settings_cache: None) -> None:
    assert cfg.get_settings().uzum_open_service_url == "https://www.uzumbank.uz/open-service"


def test_uzum_password_is_read_from_env(
    monkeypatch: pytest.MonkeyPatch,
    _clear_settings_cache: None,
) -> None:
    monkeypatch.setenv("UZUM_PASSWORD", "prod-password-123")
    assert cfg.get_settings().uzum_password == "prod-password-123"


def test_uzum_test_password_is_read_from_env(
    monkeypatch: pytest.MonkeyPatch,
    _clear_settings_cache: None,
) -> None:
    monkeypatch.setenv("UZUM_TEST_PASSWORD", "sandbox-password-123")
    assert cfg.get_settings().uzum_test_password == "sandbox-password-123"


def test_uzum_service_id_parses_from_env_as_int(
    monkeypatch: pytest.MonkeyPatch,
    _clear_settings_cache: None,
) -> None:
    monkeypatch.setenv("UZUM_SERVICE_ID", "123456")
    settings = cfg.get_settings()
    assert settings.uzum_service_id == 123456
    assert isinstance(settings.uzum_service_id, int)
