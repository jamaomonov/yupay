"""A buyer deleting their own account (`DELETE /auth/me`, ``auth.account_deletion``).

Pinned here: the account is tombstoned, not erased — its row stays; the session that asked
dies at once; the call needs an Idempotency-Key; an operator cannot delete itself; and a
Telegram or Steam identity signing in again gets a fresh account that takes the link over,
instead of a 500 on the global unique link or a session for the deleted account.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.auth.account_deletion import delete_account
from yupay.modules.auth.telegram import TelegramUser
from yupay.modules.push.models import PushDevice
from yupay.modules.push.service import register_device
from yupay.modules.users.models import SteamLink, User
from yupay.modules.users.service import upsert_user_by_steam, upsert_user_by_telegram

from tests.integration.test_payments_wallet_gateway import _login_user

pytestmark = pytest.mark.asyncio


def _tg(tg_id: int) -> TelegramUser:
    return TelegramUser(
        id=tg_id,
        first_name="Buyer",
        last_name=None,
        username="buyer_tg",
        language_code="ru",
        is_premium=False,
        photo_url=None,
    )


async def test_deleting_tombstones_the_account_and_ends_the_session(client: AsyncClient) -> None:
    token, user_id = await _login_user(client, 771_000_001)
    auth = {"Authorization": f"Bearer {token}"}

    refused = await client.delete("/api/v1/auth/me", headers=auth)
    assert refused.status_code == 422  # no Idempotency-Key

    gone = await client.delete("/api/v1/auth/me", headers={**auth, "Idempotency-Key": new_id()})
    assert gone.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=auth)).status_code == 401

    # The same Telegram identity signs in again: a new, empty account.
    _, again = await _login_user(client, 771_000_001)
    assert again != user_id


async def test_the_row_stays_and_the_devices_stop(db_session: AsyncSession) -> None:
    user = await upsert_user_by_telegram(db_session, _tg(771_000_002))
    device = await register_device(
        db_session,
        user_id=user.id,
        token="ExponentPushToken[deletiontest00001]",
        platform="ios",
        app_version=None,
    )
    await delete_account(db_session, user)

    row = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert row.deleted_at is not None
    refreshed = (
        await db_session.execute(select(PushDevice).where(PushDevice.id == device.id))
    ).scalar_one()
    assert refreshed.disabled_reason == "account_deleted"


async def test_an_operator_cannot_delete_itself(db_session: AsyncSession) -> None:
    user = await upsert_user_by_telegram(db_session, _tg(771_000_003))
    user.roles = ["admin"]
    await db_session.flush()
    with pytest.raises(Exception, match="operator"):
        await delete_account(db_session, user)
    assert user.deleted_at is None


async def test_telegram_identity_moves_to_a_fresh_account(db_session: AsyncSession) -> None:
    old = await upsert_user_by_telegram(db_session, _tg(771_000_004))
    await delete_account(db_session, old)

    fresh = await upsert_user_by_telegram(db_session, _tg(771_000_004))
    assert fresh.id != old.id
    assert fresh.deleted_at is None
    assert fresh.telegram_link is not None
    assert fresh.telegram_link.tg_user_id == 771_000_004
    # A later sign-in finds the fresh account, not another new one.
    assert (await upsert_user_by_telegram(db_session, _tg(771_000_004))).id == fresh.id


async def test_steam_identity_moves_to_a_fresh_account(db_session: AsyncSession) -> None:
    old = await upsert_user_by_steam(db_session, steam_id=76561190000000001, persona_name="P")
    await delete_account(db_session, old)

    fresh = await upsert_user_by_steam(db_session, steam_id=76561190000000001, persona_name="P")
    assert fresh.id != old.id
    assert fresh.deleted_at is None
    link = (
        await db_session.execute(select(SteamLink).where(SteamLink.steam_id == 76561190000000001))
    ).scalar_one()
    assert link.user_id == fresh.id
