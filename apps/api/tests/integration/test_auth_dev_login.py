"""Dev-only admin login (`POST /api/v1/auth/admin-dev`) hardening.

Covers the two security guards added to the stop-gap endpoint:

- it refuses to run while the credentials are still the compiled-in defaults, and
- it authenticates (constant-time) against real, operator-set credentials.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _uniq_ip() -> dict[str, str]:
    """A unique X-Forwarded-For per call so the per-IP rate guard never bleeds across tests."""
    return {"X-Forwarded-For": f"198.51.100.{uuid.uuid4().int % 256}"}


async def test_dev_login_refuses_default_credentials(
    integration_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setenv("ADMIN_DEV_LOGIN_ENABLED", "true")
    # ADMIN_DEV_LOGIN / ADMIN_DEV_PASSWORD left at the compiled-in "admin" defaults.
    from yupay.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        r = await integration_client.post(
            "/api/v1/auth/admin-dev",
            json={"login": "admin", "password": "admin"},
            headers=_uniq_ip(),
        )
        assert r.status_code == 403, r.text
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_dev_login_succeeds_with_real_credentials(
    integration_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setenv("ADMIN_DEV_LOGIN_ENABLED", "true")
    monkeypatch.setenv("ADMIN_DEV_LOGIN", "realadmin")
    monkeypatch.setenv("ADMIN_DEV_PASSWORD", "realsecret123")
    from yupay.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        ok = await integration_client.post(
            "/api/v1/auth/admin-dev",
            json={"login": "realadmin", "password": "realsecret123"},
            headers=_uniq_ip(),
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["access_token"]

        bad = await integration_client.post(
            "/api/v1/auth/admin-dev",
            json={"login": "realadmin", "password": "WRONGWRONG"},
            headers=_uniq_ip(),
        )
        assert bad.status_code == 401, bad.text
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]
