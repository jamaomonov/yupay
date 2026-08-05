"""Concurrent refresh-token rotation must not clone a session (TOCTOU guard).

``refresh_session`` reads the ``auth_sessions`` row, checks ``revoked_at IS
NULL``, then writes ``revoked_at``. Without row locking, two requests racing
with the *same* refresh token both read it as un-revoked, both pass the check,
and both mint a new session — a stolen refresh token can be replayed alongside
the legitimate use and the reuse-detection trip-wire (ADR-0007) never fires.

The fix serialises concurrent refreshers on the row (``SELECT ... FOR UPDATE``):
exactly one rotates; the loser blocks on the lock, then observes the now-revoked
row and trips reuse detection, which revokes every session for the user.

This test forces the interleaving deterministically instead of hoping the
scheduler hits the window: the first refresher pauses *after* it has read the
row but *before* it writes the revocation (inside ``get_user_by_id``, which the
service calls in exactly that gap), while the second refresher runs. Under the
bug both commit; under the fix the second blocks on the row lock and is then
rejected as reuse.
"""

from __future__ import annotations

import asyncio

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth import service as auth_svc
from yupay.modules.auth.models import AuthSession
from yupay.modules.users.models import User
from yupay.modules.users.service import get_user_by_id

pytestmark = pytest.mark.asyncio


async def _refresh(factory: async_sessionmaker[AsyncSession], token: str) -> str:
    """Run one full refresh in its own committed transaction; return outcome tag."""
    async with factory() as session:
        try:
            await auth_svc.refresh_session(session, token)
        except UnauthorizedError:
            await session.commit()  # let any reuse-detection revocations persist
            return "rejected"
        await session.commit()
        return "ok"


async def test_concurrent_refresh_same_token_rotates_once(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # A user with one open session → a valid refresh token to race on.
    async with factory() as setup:
        user = User(id=new_id(), email="race@yupay.test", password_hash="x")
        setup.add(user)
        await setup.flush()
        tokens = await auth_svc._open_session(setup, user=user, settings=get_settings())
        await setup.commit()
        user_id = user.id

    # Hold the first refresher open in the read→write window: get_user_by_id is
    # called after the `revoked_at IS NULL` check and before the revocation write.
    orig_get_user = get_user_by_id
    first_in_window = asyncio.Event()
    release_first = asyncio.Event()
    state = {"paused": False}

    async def _paused_get_user(db: AsyncSession, uid: str):  # type: ignore[no-untyped-def]
        if not state["paused"]:
            state["paused"] = True
            first_in_window.set()
            await release_first.wait()
        return await orig_get_user(db, uid)

    monkeypatch.setattr(auth_svc, "get_user_by_id", _paused_get_user)

    async def _run_a() -> str:
        return await _refresh(factory, tokens.refresh_token)

    async def _run_b() -> str:
        await first_in_window.wait()  # start only once A is parked past its read
        task = asyncio.ensure_future(_refresh(factory, tokens.refresh_token))
        # Give B time to issue its SELECT — under the fix it blocks on A's row
        # lock here; under the bug it sails past and commits a second rotation.
        await asyncio.sleep(0.3)
        release_first.set()  # let A finish; B (if blocked) then unblocks
        return await task

    a_result, b_result = await asyncio.gather(_run_a(), _run_b())

    # Exactly one rotation succeeds; the other is rejected as reuse.
    assert sorted([a_result, b_result]) == ["ok", "rejected"], [a_result, b_result]

    # Reuse detection burned the user's sessions down: the winning rotation's
    # freshly-minted session is itself revoked by the loser's trip-wire.
    async with factory() as check:
        active = (
            await check.execute(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            )
        ).scalar_one()
    assert active == 0
