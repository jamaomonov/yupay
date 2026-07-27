"""Integration tests for ``POST /api/v1/auth/telegram/widget/admin``.

The admin panel logs in through a dedicated Telegram Login Widget. The endpoint
verifies the widget signature (against ``admin_telegram_bot_token``, falling back
to ``telegram_bot_token`` in single-bot setups) and only mints a session for users
carrying the ``admin`` role.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"  # matches the conftest-managed TELEGRAM_BOT_TOKEN


def _sign_widget(fields: dict[str, str]) -> dict[str, str]:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    return {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}


def _typed(payload: dict[str, str]) -> dict[str, object]:
    return {
        "id": int(payload["id"]),
        "first_name": payload["first_name"],
        "auth_date": int(payload["auth_date"]),
        "hash": payload["hash"],
    }


async def test_admin_widget_rejects_non_admin(
    integration_client: AsyncClient, fixed_now: int
) -> None:
    payload = _sign_widget({"id": "9001", "first_name": "Rando", "auth_date": str(fixed_now)})
    r = await integration_client.post("/api/v1/auth/telegram/widget/admin", json=_typed(payload))
    assert r.status_code == 403, r.text


async def test_admin_widget_rejects_tampered_hash(
    integration_client: AsyncClient, fixed_now: int
) -> None:
    payload = _sign_widget({"id": "9002", "first_name": "Tamper", "auth_date": str(fixed_now)})
    payload["hash"] = "0" * 64
    r = await integration_client.post("/api/v1/auth/telegram/widget/admin", json=_typed(payload))
    assert r.status_code == 401, r.text


async def test_admin_widget_admin_succeeds(
    integration_client: AsyncClient, db_session, fixed_now: int
) -> None:
    # First create the user via the customer widget (no role gate), then promote.
    seed = _sign_widget({"id": "9003", "first_name": "Boss", "auth_date": str(fixed_now)})
    reg = await integration_client.post("/api/v1/auth/telegram/widget", json=_typed(seed))
    assert reg.status_code == 200, reg.text
    me = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {reg.json()['access_token']}"},
    )
    user_id = me.json()["id"]
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()

    # Fresh payload (new auth_date => distinct signature, so the single-use replay guard
    # doesn't confuse this second login with the seed login above), same Telegram id.
    payload = _sign_widget({"id": "9003", "first_name": "Boss", "auth_date": str(fixed_now + 5)})
    r = await integration_client.post("/api/v1/auth/telegram/widget/admin", json=_typed(payload))
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


@pytest.fixture
def fixed_now() -> int:
    import time

    return int(time.time())
