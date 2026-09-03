"""Admin settings for Steam Gifts: `GET`/`PATCH /admin/gifts/settings`.

Covers the env-seeded default, a persisted margin change, idempotency-key
replay (mirroring `test_admin_providers.test_set_state_idempotency_key_
replays_cached_response`), and the 403 a non-admin gets.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.gifts.models import SteamGiftSettings
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


async def _admin_headers(client: AsyncClient, db: AsyncSession, tg_id: int) -> dict[str, str]:
    token = await _login_user(client, tg_id=tg_id)
    await _grant_admin(db, tg_id=tg_id)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_get_default_then_patch_persists_and_replays_idempotently(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The full admin lifecycle: seeded default, a persisted change, a replay.

    No row exists yet, so the first `GET` must answer from
    `settings.steam_gifts_margin_percent` (the env default, 10) rather than
    404 or crash. `steam_gift_settings` is in the integration suite's
    per-test TRUNCATE list (see `conftest.py`), so this test's `margin=77`
    write at the end never leaks into another test — every test, in this
    module or any other, starts from an empty table.
    """
    headers = await _admin_headers(integration_client, db_session, tg_id=9001)

    get_default = await integration_client.get("/api/v1/admin/gifts/settings", headers=headers)
    assert get_default.status_code == 200, get_default.text
    default_body = get_default.json()
    assert default_body["margin_percent"] == "10"
    assert default_body["enabled"] is False
    # 2026-09-03: the code default became the buyer-facing country "UZ"
    # (was the zone label "CIS") — see config.py's steam_gifts_region_default.
    assert default_body["region_default"] == "UZ"
    assert default_body["regions"] == ["CIS", "RU", "KZ", "UA"]

    key = "gifts-margin-idem-0000001"
    first_patch = await integration_client.patch(
        "/api/v1/admin/gifts/settings",
        headers={**headers, "Idempotency-Key": key},
        json={"margin_percent": "12.5"},
    )
    assert first_patch.status_code == 200, first_patch.text
    assert first_patch.json()["margin_percent"] == "12.5"

    get_after_patch = await integration_client.get("/api/v1/admin/gifts/settings", headers=headers)
    assert get_after_patch.json()["margin_percent"] == "12.5"

    row = (
        await db_session.execute(select(SteamGiftSettings).where(SteamGiftSettings.id == 1))
    ).scalar_one()
    assert row.margin_percent == Decimal("12.5")
    assert row.updated_by is not None

    # Mutate the row out-of-band (bypassing the route entirely) so a live
    # re-execution of the handler would be observably different from the
    # cached first response.
    await db_session.execute(
        update(SteamGiftSettings)
        .where(SteamGiftSettings.id == 1)
        .values(margin_percent=Decimal("77"))
    )
    await db_session.commit()

    replay = await integration_client.patch(
        "/api/v1/admin/gifts/settings",
        headers={**headers, "Idempotency-Key": key},
        json={"margin_percent": "99"},  # different body — the replay must ignore it
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first_patch.json()
    assert replay.json()["margin_percent"] == "12.5"

    # The out-of-band mutation is still in place — the replay never called
    # `save_margin_percent` a second time.
    row_after_replay = (
        await db_session.execute(select(SteamGiftSettings).where(SteamGiftSettings.id == 1))
    ).scalar_one()
    assert row_after_replay.margin_percent == Decimal("77")


async def test_non_admin_gets_403(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_user(integration_client, tg_id=9002)
    headers = {"Authorization": f"Bearer {token}"}

    r = await integration_client.get("/api/v1/admin/gifts/settings", headers=headers)
    assert r.status_code == 403

    patch = await integration_client.patch(
        "/api/v1/admin/gifts/settings",
        headers={**headers, "Idempotency-Key": "not-an-admin-idempotency-key"},
        json={"margin_percent": "5"},
    )
    assert patch.status_code == 403
