"""Revoking a session must invalidate its already-issued access tokens now.

Access tokens are short-lived (15 min) JWTs that carry the session id (``sid``)
but were validated only against a per-``jti`` blocklist — which is populated
solely on an explicit ``logout`` that presents the access token. So revoking a
session by other means (reuse-detection trip-wire, password reset's revoke-all,
logout-all) left every outstanding access token for that session usable for up
to its full lifetime. This pins the fix: a revoked session's live access token
is rejected on the next request.
"""

from __future__ import annotations

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order

from sqlalchemy.ext.asyncio import async_sessionmaker
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth import service as auth_svc
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def test_revoke_all_invalidates_live_access_token(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async with factory() as db:
        user = User(id=new_id(), email="revoke@yupay.test", password_hash="x")
        db.add(user)
        await db.flush()
        tokens = await auth_svc._open_session(db, user=user, settings=get_settings())
        await db.commit()
        uid = user.id
    access = tokens.access_token

    # Sanity: the freshly-minted access token authenticates.
    async with factory() as db:
        assert (await auth_svc.current_user(db, access)).id == uid

    # Revoke every session for the user (as reuse-detection / password reset do).
    async with factory() as db:
        await auth_svc._revoke_all_for_user(db, uid)
        await db.commit()

    # The still-unexpired access token must now be rejected, not linger 15 min.
    async with factory() as db:
        with pytest.raises(UnauthorizedError):
            await auth_svc.current_user(db, access)


async def test_logout_invalidates_live_access_token_without_presenting_it(db_engine) -> None:
    """logout revokes the session row; its access token must die even when the
    logout request didn't carry the access token (only the refresh cookie)."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async with factory() as db:
        user = User(id=new_id(), email="logout@yupay.test", password_hash="x")
        db.add(user)
        await db.flush()
        tokens = await auth_svc._open_session(db, user=user, settings=get_settings())
        await db.commit()
    access = tokens.access_token
    refresh = tokens.refresh_token

    async with factory() as db:
        # No access_token passed — only the refresh token, like the cookie flow.
        await auth_svc.logout(db, refresh)
        await db.commit()

    async with factory() as db:
        with pytest.raises(UnauthorizedError):
            await auth_svc.current_user(db, access)
