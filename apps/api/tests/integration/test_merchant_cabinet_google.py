"""Google sign-in for the merchant cabinet (``cabinet_google``).

Pinned: an unverified Google email never gets in; an unknown address
registers only with the offer accepted; a Google sign-in on an unconfirmed
account kills the password somebody may have planted there; a frozen
merchant stays out.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.errors import AccountSuspendedError, NotFoundError, UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth import google as google_module
from yupay.modules.auth.google import GoogleAuthError, GoogleUser
from yupay.modules.auth.security import hash_password, verify_password
from yupay.modules.merchants.cabinet_auth import OFFER_VERSION
from yupay.modules.merchants.cabinet_google import google_sign_in
from yupay.modules.merchants.models import Merchant, MerchantUser

pytestmark = pytest.mark.asyncio

PLANTED = "planted-password-123"


def _verifier(email: str, *, verified: bool = True, name: str | None = "Shop Owner"):  # type: ignore[no-untyped-def]
    async def verify(token: str) -> GoogleUser:
        assert token == "tok"
        return GoogleUser(sub="g-1", email=email, email_verified=verified, name=name, picture=None)

    return verify


async def _merchant(
    db: AsyncSession, email: str, *, confirmed: bool = True, status: str = "active"
) -> MerchantUser:
    merchant = Merchant(id=new_id(), title="Existing", status=status)
    user = MerchantUser(
        id=new_id(),
        merchant_id=merchant.id,
        email=email,
        password_hash=await hash_password(PLANTED),
        email_confirmed_at=now() if confirmed else None,
        offer_version=OFFER_VERSION,
        offer_accepted_at=now(),
    )
    db.add(merchant)
    await db.flush()
    db.add(user)
    await db.flush()
    return user


async def _users(db: AsyncSession, email: str) -> list[MerchantUser]:
    return list(
        (await db.execute(select(MerchantUser).where(MerchantUser.email == email))).scalars()
    )


async def test_existing_operator_signs_in(db_session: AsyncSession) -> None:
    email = f"op-{new_id()}@example.test"
    user = await _merchant(db_session, email)
    tokens = await google_sign_in(
        db_session, access_token="tok", accept_offer=False, verifier=_verifier(email.upper())
    )
    assert tokens.access_token
    assert [u.id for u in await _users(db_session, email)] == [user.id]
    # A confirmed operator keeps their password.
    assert await verify_password(PLANTED, user.password_hash)


async def test_unknown_address_without_offer_is_not_registered(db_session: AsyncSession) -> None:
    email = f"new-{new_id()}@example.test"
    with pytest.raises(NotFoundError) as info:
        await google_sign_in(
            db_session, access_token="tok", accept_offer=False, verifier=_verifier(email)
        )
    assert info.value.extra.get("code") == "merchant_not_registered"
    assert await _users(db_session, email) == []


async def test_unknown_address_with_offer_registers_confirmed(db_session: AsyncSession) -> None:
    email = f"new-{new_id()}@example.test"
    tokens = await google_sign_in(
        db_session,
        access_token="tok",
        accept_offer=True,
        title="  My Channel  ",
        verifier=_verifier(email),
    )
    assert tokens.access_token
    [user] = await _users(db_session, email)
    assert user.email_confirmed_at is not None
    assert user.offer_version == OFFER_VERSION
    merchant = await db_session.get(Merchant, user.merchant_id)
    assert merchant is not None
    assert merchant.title == "My Channel"


async def test_registration_title_falls_back_to_google_name(db_session: AsyncSession) -> None:
    email = f"new-{new_id()}@example.test"
    await google_sign_in(
        db_session, access_token="tok", accept_offer=True, title=" ", verifier=_verifier(email)
    )
    [user] = await _users(db_session, email)
    merchant = await db_session.get(Merchant, user.merchant_id)
    assert merchant is not None
    assert merchant.title == "Shop Owner"


async def test_unverified_google_email_is_refused(db_session: AsyncSession) -> None:
    email = f"op-{new_id()}@example.test"
    await _merchant(db_session, email)
    with pytest.raises(UnauthorizedError):
        await google_sign_in(
            db_session,
            access_token="tok",
            accept_offer=True,
            verifier=_verifier(email, verified=False),
        )


async def test_rejected_token_is_unauthorized(db_session: AsyncSession) -> None:
    async def verify(token: str) -> GoogleUser:
        raise GoogleAuthError("token was minted for another application")

    with pytest.raises(UnauthorizedError):
        await google_sign_in(db_session, access_token="tok", accept_offer=True, verifier=verify)


async def test_unconfirmed_account_is_confirmed_and_planted_password_dies(
    db_session: AsyncSession,
) -> None:
    email = f"op-{new_id()}@example.test"
    user = await _merchant(db_session, email, confirmed=False)
    await google_sign_in(
        db_session, access_token="tok", accept_offer=False, verifier=_verifier(email)
    )
    assert user.email_confirmed_at is not None
    assert not await verify_password(PLANTED, user.password_hash)


async def test_frozen_merchant_stays_out(db_session: AsyncSession) -> None:
    email = f"op-{new_id()}@example.test"
    await _merchant(db_session, email, status="frozen")
    with pytest.raises(AccountSuspendedError):
        await google_sign_in(
            db_session, access_token="tok", accept_offer=False, verifier=_verifier(email)
        )


async def test_route_answers_404_code_for_unknown_address(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    email = f"new-{new_id()}@example.test"
    monkeypatch.setattr(google_module, "verify_credential", _verifier(email))
    r = await client.post("/merchant/cabinet/google", json={"access_token": "tok"})
    assert r.status_code == 404, r.text
    assert r.json().get("code") == "merchant_not_registered"

    r = await client.post(
        "/merchant/cabinet/google",
        json={"access_token": "tok", "accept_offer": True, "title": "Chan"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    count = await db_session.scalar(
        select(func.count()).select_from(MerchantUser).where(MerchantUser.email == email)
    )
    assert count == 1
