"""One inbox, one account; a daily cap per IP; one verification mail per inbox per cooldown.

Prod, 2026-11-01: 152 registrations on ``x+b…@gmail.com`` in an hour.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

PW = "s3cret-passw0rd"


async def _register(client: AsyncClient, email: str, ip: str = "198.51.100.7") -> int:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "locale": "ru"},
        headers={"X-Forwarded-For": ip},
    )
    return r.status_code


async def test_plus_and_dot_variants_of_a_gmail_inbox_are_refused(
    integration_client: AsyncClient,
) -> None:
    assert await _register(integration_client, "one.box@gmail.com") == 201
    for variant in ("one.box+b1234@gmail.com", "onebox@gmail.com", "o.n.e.box@googlemail.com"):
        assert await _register(integration_client, variant) == 409, variant
    # Another inbox is still free.
    assert await _register(integration_client, "other.box+x@gmail.com") == 201


async def test_the_daily_cap_trips_per_ip(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_REGISTER_DAILY_MAX", "2")
    from yupay.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        codes = [
            await _register(integration_client, f"cap-{i}@example.com", ip="203.0.113.9")
            for i in range(3)
        ]
        assert codes == [201, 201, 429]
        # Another address is not charged for it.
        assert await _register(integration_client, "cap-x@example.com", ip="203.0.113.10") == 201
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_resend_is_sent_once_per_mailbox_per_cooldown(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await _register(integration_client, "cool.down@gmail.com") == 201
    sent: list[str] = []

    async def _fake(db: object, *, email: str, **_: object) -> None:
        sent.append(email)

    monkeypatch.setattr("yupay.modules.auth.routes.resend_verification", _fake)
    for email in ("cool.down@gmail.com", "cooldown+again@gmail.com"):
        r = await integration_client.post(
            "/api/v1/auth/resend-verification",
            json={"email": email},
            headers={"X-Forwarded-For": "198.51.100.8"},
        )
        assert r.status_code == 204, r.text
    assert sent == ["cool.down@gmail.com"]
