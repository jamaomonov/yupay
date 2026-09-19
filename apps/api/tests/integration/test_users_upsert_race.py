"""Two concurrent first-sight logins for the same identity must not 500.

Sentry, production, 2026-09-18: ``POST /api/v1/auth/telegram/webapp`` ->
``asyncpg.UniqueViolationError: duplicate key value violates unique
constraint "uq_telegram_links_tg_user_id"``, raised from the final
``session.add(user); session.add(link); await session.flush()`` in
``upsert_user_by_telegram``. Two brand-new-user requests for the same
Telegram id both read "not found" and both insert -- the two minted ULIDs in
the Sentry event shared a time prefix, so this was a genuine race (a mini
app firing auth twice, or a double tap), not stale data.

The same read-then-insert shape is in ``upsert_user_by_steam`` (unique on
``steam_id``). Both are pinned here by forcing the actual interleaving
deterministically: one session's lookup is paused *after* it has read "not
found" but *before* it inserts, while a second session runs the full upsert
to completion (insert + commit); only then is the first released to attempt
its own insert and collide -- the same technique
``test_auth_refresh_race.py`` uses for the refresh-rotation race.

The Google path's equivalent race (unique on ``users.email``) is pinned in
``test_auth_google.py`` instead, since it lives in ``auth.service``.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yupay.modules.auth.telegram import TelegramUser
from yupay.modules.users import service as users_service
from yupay.modules.users.models import SteamLink, TelegramLink, User

pytestmark = pytest.mark.asyncio


def _tg_user(tg_id: int) -> TelegramUser:
    return TelegramUser(
        id=tg_id,
        first_name="Racer",
        last_name=None,
        username="racer_tg",
        language_code="ru",
        is_premium=False,
        photo_url=None,
    )


async def test_concurrent_first_sight_telegram_login_does_not_500(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    tg_id = 8_999_059_550  # the id from the Sentry event, for flavour

    # Hold the first caller (A) open in the read->write gap: get_user_by_telegram_id
    # is called at the very top of upsert_user_by_telegram, right before the
    # branch that decides "found" vs "must insert".
    orig_lookup = users_service.get_user_by_telegram_id
    first_in_window = asyncio.Event()
    release_first = asyncio.Event()
    state = {"paused": False}

    async def _paused_lookup(session: AsyncSession, tgid: int) -> User | None:
        result = await orig_lookup(session, tgid)
        if tgid == tg_id and not state["paused"]:
            state["paused"] = True
            first_in_window.set()
            await release_first.wait()
        return result

    monkeypatch.setattr(users_service, "get_user_by_telegram_id", _paused_lookup)

    async def _run_a() -> str:
        async with factory() as session:
            user = await users_service.upsert_user_by_telegram(session, _tg_user(tg_id))
            await session.commit()
            return user.id

    async def _run_b() -> str:
        await first_in_window.wait()  # start only once A is parked past its read
        async with factory() as session:
            user = await users_service.upsert_user_by_telegram(session, _tg_user(tg_id))
            await session.commit()
        release_first.set()  # let A resume and hit the collision
        return user.id

    a_id, b_id = await asyncio.gather(_run_a(), _run_b())

    # Both callers end up pointing at the same, single user row -- the loser
    # recovers by re-reading the winner, not by creating a second one.
    assert a_id == b_id

    async with factory() as check:
        link_count = (
            await check.execute(
                select(func.count())
                .select_from(TelegramLink)
                .where(TelegramLink.tg_user_id == tg_id)
            )
        ).scalar_one()
        user_count = (
            await check.execute(select(func.count()).select_from(User).where(User.id == a_id))
        ).scalar_one()
    assert link_count == 1
    assert user_count == 1


async def test_concurrent_first_sight_steam_login_does_not_500(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    steam_id = 76_561_198_000_000_099

    # Same technique, pausing users_service._get_steam_link instead --
    # the SteamLink equivalent of get_user_by_telegram_id, called at the top
    # of upsert_user_by_steam right before the found/insert branch.
    orig_lookup = users_service._get_steam_link
    first_in_window = asyncio.Event()
    release_first = asyncio.Event()
    state = {"paused": False}

    async def _paused_lookup(session: AsyncSession, sid: int) -> SteamLink | None:
        result = await orig_lookup(session, sid)
        if sid == steam_id and not state["paused"]:
            state["paused"] = True
            first_in_window.set()
            await release_first.wait()
        return result

    monkeypatch.setattr(users_service, "_get_steam_link", _paused_lookup)

    async def _run_a() -> str:
        async with factory() as session:
            user = await users_service.upsert_user_by_steam(
                session, steam_id=steam_id, persona_name="Racer", avatar_url=None
            )
            await session.commit()
            return user.id

    async def _run_b() -> str:
        await first_in_window.wait()
        async with factory() as session:
            user = await users_service.upsert_user_by_steam(
                session, steam_id=steam_id, persona_name="Racer", avatar_url=None
            )
            await session.commit()
        release_first.set()
        return user.id

    a_id, b_id = await asyncio.gather(_run_a(), _run_b())

    assert a_id == b_id

    async with factory() as check:
        link_count = (
            await check.execute(
                select(func.count()).select_from(SteamLink).where(SteamLink.steam_id == steam_id)
            )
        ).scalar_one()
        user_count = (
            await check.execute(select(func.count()).select_from(User).where(User.id == a_id))
        ).scalar_one()
    assert link_count == 1
    assert user_count == 1
