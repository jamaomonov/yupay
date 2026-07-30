"""Password login is blocked until the account's email is verified.

Also covers Task 2 of the phase-3 web-orders flow: registration no longer
opens a session (``verification_required``), ``POST /auth/verify-email``
opens one instead (auto-login), and ``POST /auth/resend-verification`` never
reveals whether an email exists or its verification state.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from yupay.modules.users.models import User


@pytest.mark.asyncio
async def test_login_blocked_until_verified(integration_client: AsyncClient, db_session) -> None:
    email = "verify-gate@example.com"
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "s3cret-passw0rd", "locale": "ru"},
    )
    assert reg.status_code == 201, reg.text
    # Registration does NOT hand back a session (Task 2): just an
    # acknowledgement that verification is required, no tokens, no cookie.
    body = reg.json()
    assert body == {"status": "verification_required", "email": email}
    assert "access_token" not in body
    assert "refresh_token" not in reg.cookies

    login = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-passw0rd"},
    )
    assert login.status_code == 403, login.text
    assert login.json()["type"].endswith("/email-unverified")

    # Prove verification unblocks login: mint the same verify token the
    # register flow's email would carry (there is no capturing test mailer in
    # this suite), resolving the user id via a direct DB lookup by email
    # since register no longer returns an access token to resolve it from.
    from yupay.modules.auth import jwt as authjwt

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    token = authjwt.mint_email_verify(sub=user.id)

    verify = await integration_client.post("/api/v1/auth/verify-email", json={"token": token})
    # Verify-email now auto-logs-in: a session is opened (Task 2).
    assert verify.status_code == 200, verify.text
    verify_body = verify.json()
    assert verify_body["access_token"]
    assert "refresh_token" not in verify_body
    assert verify.cookies.get("refresh_token")

    unblocked = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-passw0rd"},
    )
    assert unblocked.status_code == 200, unblocked.text
    assert unblocked.json()["access_token"]


@pytest.mark.asyncio
async def test_resend_verification_is_non_enumerating(
    integration_client: AsyncClient, db_session
) -> None:
    email = "resend-me@example.com"
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "s3cret-passw0rd", "locale": "ru"},
    )
    assert reg.status_code == 201, reg.text

    # A known, unverified email: 204, no body content, no way to tell the
    # request "did" anything from the response alone.
    known = await integration_client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert known.status_code == 204, known.text
    assert known.text == ""

    # A completely unknown email: identical 204 response — no enumeration.
    unknown = await integration_client.post(
        "/api/v1/auth/resend-verification", json={"email": "nobody-at-all@example.com"}
    )
    assert unknown.status_code == 204, unknown.text

    # Resend never verifies or logs anyone in by itself — login stays blocked.
    login = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-passw0rd"},
    )
    assert login.status_code == 403


@pytest.mark.asyncio
async def test_resend_verification_for_already_verified_email_is_still_204(
    integration_client: AsyncClient, db_session
) -> None:
    email = "already-verified@example.com"
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "s3cret-passw0rd", "locale": "ru"},
    )
    assert reg.status_code == 201, reg.text

    from yupay.modules.auth import jwt as authjwt

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    token = authjwt.mint_email_verify(sub=user.id)
    verify = await integration_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200, verify.text

    # Already verified: still 204, and — per the non-enumeration contract —
    # indistinguishable from the unverified/unknown cases above.
    resend = await integration_client.post(
        "/api/v1/auth/resend-verification", json={"email": email}
    )
    assert resend.status_code == 204, resend.text
