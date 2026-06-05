"""IP guard returns 429 after the configured threshold."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_login_ip_guard_trips(integration_client, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "3")
    from yupay.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    # Use a unique IP per run so leftover Redis counters from prior runs don't interfere.
    unique_octet = uuid.uuid4().hex[:8]
    test_ip = f"203.0.113.{int(unique_octet[:2], 16) % 256}"
    headers = {"X-Forwarded-For": test_ip}

    # Flush the specific guard key so this test is deterministic on repeat runs.
    from yupay.core.redis import get_redis

    login_key = f"auth:ipguard:login:{test_ip}"
    await get_redis().delete(login_key)

    statuses = []
    for _ in range(5):
        r = await integration_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "whatever12"},
            headers=headers,
        )
        statuses.append(r.status_code)
    assert 429 in statuses
    get_settings.cache_clear()  # type: ignore[attr-defined]
