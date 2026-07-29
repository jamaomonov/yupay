"""Password login is blocked until the account's email is verified."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_blocked_until_verified(integration_client: AsyncClient, db_session) -> None:
    email = "verify-gate@example.com"
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "s3cret-passw0rd", "locale": "ru"},
    )
    assert reg.status_code in (200, 201, 202), reg.text
    # Registration does NOT hand back a session anymore (Task 2 enforces this;
    # this task only asserts login is blocked while unverified).
    login = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-passw0rd"},
    )
    assert login.status_code == 403, login.text
    assert login.json()["type"].endswith("/email-unverified")

    # Prove verification unblocks login: mint the same verify token the
    # register flow's email would carry (there is no capturing test mailer in
    # this suite — the existing `test_verify_email_marks_verified` test uses
    # this same `current_user` + `mint_email_verify` pattern), drive it
    # through the real `/auth/verify-email` endpoint, then retry login.
    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    # Register did not return a session in this task's target end-state, but
    # today it still does (Task 2 removes that) — use it only to resolve the
    # user id, exactly like the existing verify-email test does.
    access = reg.json()["access_token"]
    user = await current_user(db_session, access)
    token = authjwt.mint_email_verify(sub=user.id)

    verify = await integration_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 204, verify.text

    unblocked = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-passw0rd"},
    )
    assert unblocked.status_code == 200, unblocked.text
    assert unblocked.json()["access_token"]
