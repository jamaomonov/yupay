"""resolve_request_actor: Bearer → user, Guest+email → guest, mismatches raise."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.modules.auth.deps import resolve_request_actor
from yupay.modules.auth.jwt import mint_access

from tests.integration.test_reviews_service import _make_user

pytestmark = pytest.mark.asyncio


def _req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


async def test_bearer_resolves_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, display_name="Alice")
    await db_session.commit()
    actor = await resolve_request_actor(
        _req({"Authorization": f"Bearer {mint_access(sub=user.id, sid='s1')}"}), db_session
    )
    assert actor.user_id == user.id
    assert actor.guest_email is None
    assert actor.user is not None


async def test_guest_requires_email_header(db_session: AsyncSession) -> None:
    from yupay.modules.auth.service import guest_checkout

    res = await guest_checkout(db_session, "g@x.com")
    with pytest.raises(ValidationError):
        await resolve_request_actor(
            _req({"Authorization": f"Guest {res.access_token}"}), db_session
        )


async def test_guest_email_mismatch_rejected(db_session: AsyncSession) -> None:
    from yupay.modules.auth.service import guest_checkout

    res = await guest_checkout(db_session, "g@x.com")
    with pytest.raises(UnauthorizedError):
        await resolve_request_actor(
            _req({"Authorization": f"Guest {res.access_token}", "X-Guest-Email": "other@x.com"}),
            db_session,
        )
