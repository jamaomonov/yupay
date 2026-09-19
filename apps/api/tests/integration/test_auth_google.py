"""Google sign-in: identity comes from a verified ID token, linking by email.

The two behaviours that carry the account-takeover risk are pinned here: an
unverified Google email never opens a session, and a Google login landing on
an account whose email was never verified clears any password seeded there —
password login already refuses unverified accounts, so that hash could only
have been planted by someone who couldn't prove the address; making the email
verified without clearing it would have armed the planted password.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.errors import UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth.google import GoogleAuthError, GoogleUser
from yupay.modules.auth.service import google_login
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


def _google_user(email: str = "buyer@example.test", verified: bool = True) -> GoogleUser:
    return GoogleUser(
        sub="google-sub-1",
        email=email,
        email_verified=verified,
        name="Buyer Person",
        picture="https://lh3.googleusercontent.com/a/pic",
    )


async def test_first_google_login_creates_a_verified_user(db_session: AsyncSession) -> None:
    async def verify(credential: str) -> GoogleUser:
        assert credential == "tok"
        return _google_user(email=f"g-{new_id()}@example.test")

    tokens = await google_login(db_session, "tok", verifier=verify)
    assert tokens.access_token

    user = (
        await db_session.execute(
            User.__table__.select().order_by(User.__table__.c.created_at.desc()).limit(1)
        )
    ).first()
    assert user is not None
    assert user.email_verified_at is not None
    assert user.display_name == "Buyer Person"


async def test_google_login_joins_the_existing_account_for_that_email(
    db_session: AsyncSession,
) -> None:
    existing = User(
        id=new_id(),
        email="same@example.test",
        email_verified_at=now(),
        display_name="Old Name",
        locale="ru",
    )
    db_session.add(existing)
    await db_session.flush()

    async def verify(credential: str) -> GoogleUser:
        return _google_user(email="Same@Example.test")  # case must not fork accounts

    tokens = await google_login(db_session, "tok", verifier=verify)
    assert tokens.access_token
    count = (
        await db_session.execute(
            User.__table__.select().where(User.__table__.c.email == "same@example.test")
        )
    ).all()
    assert len(count) == 1


async def test_google_login_disarms_a_password_planted_on_an_unverified_email(
    db_session: AsyncSession,
) -> None:
    planted = User(
        id=new_id(),
        email="victim@example.test",
        email_verified_at=None,
        password_hash="$argon2id$fake",
        locale="ru",
    )
    db_session.add(planted)
    await db_session.flush()

    async def verify(credential: str) -> GoogleUser:
        return _google_user(email="victim@example.test")

    await google_login(db_session, "tok", verifier=verify)
    await db_session.refresh(planted)
    assert planted.email_verified_at is not None  # the real owner proved the address
    assert planted.password_hash is None  # and the planted password died with it


async def test_an_unverified_google_email_is_refused(db_session: AsyncSession) -> None:
    async def verify(credential: str) -> GoogleUser:
        return _google_user(verified=False)

    with pytest.raises(UnauthorizedError):
        await google_login(db_session, "tok", verifier=verify)


async def test_a_bad_token_is_a_401_not_a_500(db_session: AsyncSession) -> None:
    async def verify(credential: str) -> GoogleUser:
        raise GoogleAuthError("bad signature")

    with pytest.raises(UnauthorizedError):
        await google_login(db_session, "tok", verifier=verify)


async def test_an_absurdly_long_avatar_url_does_not_fail_registration(
    db_session: AsyncSession,
) -> None:
    """Sentry, production: a real Google avatar URL past 1024 chars 500'd
    ``POST /auth/google`` with ``StringDataRightTruncationError`` on the old
    ``varchar(1024)`` column. The column is now ``text`` (migration 0083),
    but the guard (``identity_guard.safe_avatar_url``) must also refuse an
    absurd value outright rather than lean on the column alone — so
    registration succeeds either way, with no avatar stored for a value this
    implausible.
    """
    absurd_url = "https://lh3.googleusercontent.com/a-/" + ("A" * 3000)
    email = f"g-{new_id()}@example.test"

    async def verify_with_long_avatar(credential: str) -> GoogleUser:
        user = _google_user(email=email)
        return GoogleUser(
            sub=user.sub,
            email=user.email,
            email_verified=user.email_verified,
            name=user.name,
            picture=absurd_url,
        )

    tokens = await google_login(db_session, "tok", verifier=verify_with_long_avatar)
    assert tokens.access_token

    row = (
        await db_session.execute(User.__table__.select().where(User.__table__.c.email == email))
    ).first()
    assert row is not None
    assert row.photo_url is None


async def test_a_normal_length_avatar_url_still_stores_it(db_session: AsyncSession) -> None:
    email = f"g-{new_id()}@example.test"

    async def verify(credential: str) -> GoogleUser:
        return _google_user(email=email)

    await google_login(db_session, "tok", verifier=verify)
    row = (
        await db_session.execute(User.__table__.select().where(User.__table__.c.email == email))
    ).first()
    assert row is not None
    assert row.photo_url == "https://lh3.googleusercontent.com/a/pic"
