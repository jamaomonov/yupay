"""A login that says it is a browser page must carry an allowed Origin.

The 2026-11-23 credential-stuffing run sent ``X-Yupay-Surface: web`` with no
``Origin``; each try cost an argon2 verify. No browser sends that, so it is
refused before the hash. The mobile app (no browser, no Origin) and callers
that name no surface are unaffected.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from yupay.core.config import get_settings

BODY = {"email": "nobody@example.com", "password": "whatever12"}


@pytest.fixture(autouse=True)
def _origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "cors_allow_origins", ["https://yupay.uz"])


@pytest.mark.parametrize("surface", ["web", "miniapp"])
async def test_browser_surface_without_origin_is_refused(
    integration_client: AsyncClient, surface: str
) -> None:
    r = await integration_client.post(
        "/api/v1/auth/login", json=BODY, headers={"X-Yupay-Surface": surface}
    )
    assert r.status_code == 403


async def test_browser_surface_from_a_foreign_origin_is_refused(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.post(
        "/api/v1/auth/login",
        json=BODY,
        headers={"X-Yupay-Surface": "web", "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Yupay-Surface": "web", "Origin": "https://yupay.uz"},
        {"X-Yupay-Surface": "mobile"},
        {},
    ],
)
async def test_real_callers_reach_the_password_check(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await integration_client.post("/api/v1/auth/login", json=BODY, headers=headers)
    assert r.status_code == 401
