"""Expired and revoked sessions must not accumulate forever.

Measured on production: 3551 of 4122 rows — 86% — were already expired or
revoked, with nothing ever deleting them. It is the fastest-growing table in
the twelve-month projection at roughly 7 sessions per order, which at the
target volume is about 13 million rows and 5GB, almost all of it garbage.

The grace period is the point of the design. A refresh token is rotated on
every use, so a row can be revoked while the client is still holding the token
that revoked it; deleting immediately turns "your session was replaced" into
"this session never existed", which is a different and much worse error to
debug from a support ticket.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.auth.models import AuthSession
from yupay.modules.auth.service import purge_stale_sessions
from yupay.modules.users.models import User

pytestmark = pytest.mark.integration


async def _user(db: AsyncSession) -> User:
    user = User(id=new_id(), email=f"purge-{new_id()[:8]}@example.com", roles=[])
    db.add(user)
    await db.flush()
    return user


def _session(user_id: str, *, expires_in: timedelta, revoked_ago: timedelta | None = None):
    """A `kind='user'` row — the check constraint ties kind, user_id and
    refresh_token_hash together. Guest sessions age out the same way."""
    return AuthSession(
        id=new_id(),
        kind="user",
        user_id=user_id,
        refresh_token_hash=new_id().replace("-", "")[:32] + new_id().replace("-", "")[:32],
        expires_at=now() + expires_in,
        revoked_at=(now() - revoked_ago) if revoked_ago is not None else None,
    )


async def test_long_expired_sessions_are_deleted(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add(_session(user.id, expires_in=timedelta(days=-30)))
    await db_session.flush()

    deleted = await purge_stale_sessions(db_session)

    assert deleted == 1


async def test_a_live_session_survives(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    keep = _session(user.id, expires_in=timedelta(days=30))
    db_session.add(keep)
    await db_session.flush()

    await purge_stale_sessions(db_session)

    remaining = await db_session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.id == keep.id)
    )
    assert remaining == 1


async def test_a_recently_expired_session_is_kept_for_the_grace_period(
    db_session: AsyncSession,
) -> None:
    """Deleting the moment a session expires turns "your session ended" into
    "this session never existed" for anyone still holding the old token."""
    user = await _user(db_session)
    fresh_corpse = _session(user.id, expires_in=timedelta(hours=-1))
    db_session.add(fresh_corpse)
    await db_session.flush()

    await purge_stale_sessions(db_session)

    remaining = await db_session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.id == fresh_corpse.id)
    )
    assert remaining == 1


async def test_a_long_revoked_session_is_deleted_even_if_not_yet_expired(
    db_session: AsyncSession,
) -> None:
    """Revocation is the other half: a logged-out session keeps a far-future
    `expires_at`, so expiry alone would never reach it."""
    user = await _user(db_session)
    db_session.add(_session(user.id, expires_in=timedelta(days=30), revoked_ago=timedelta(days=30)))
    await db_session.flush()

    deleted = await purge_stale_sessions(db_session)

    assert deleted == 1


async def test_one_sweep_is_bounded(db_session: AsyncSession) -> None:
    """The first run after this ships meets millions of rows. An unbounded
    DELETE would hold locks and bloat WAL in one transaction; the job is
    expected to catch up over several nights instead."""
    user = await _user(db_session)
    for _ in range(5):
        db_session.add(_session(user.id, expires_in=timedelta(days=-30)))
    await db_session.flush()

    deleted = await purge_stale_sessions(db_session, limit=2)

    assert deleted == 2
