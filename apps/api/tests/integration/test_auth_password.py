"""Email/password auth flows: register, login, verify, forgot, reset."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_register_creates_user_and_returns_tokens(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "newbie@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]

    me = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "newbie@example.com"


async def test_register_duplicate_email_conflicts(integration_client: AsyncClient) -> None:
    payload = {"email": "dupe@example.com", "password": "hunter2hunter2"}
    first = await integration_client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await integration_client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_password(integration_client: AsyncClient) -> None:
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "loginok@example.com", "password": "hunter2hunter2"},
    )
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "loginok@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(integration_client: AsyncClient) -> None:
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "loginbad@example.com", "password": "hunter2hunter2"},
    )
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "loginbad@example.com", "password": "WRONGWRONG"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_verify_email_marks_verified(integration_client, db_session) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "verify@example.com", "password": "hunter2hunter2"},
    )
    access = reg.json()["access_token"]
    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    user = await current_user(db_session, access)
    token = authjwt.mint_email_verify(sub=user.id)

    r = await integration_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 204, r.text

    await db_session.refresh(user)
    assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_forgot_is_non_enumerating(integration_client) -> None:
    r = await integration_client.post(
        "/api/v1/auth/password/forgot", json={"email": "ghost@example.com"}
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_reset_changes_password_and_revokes_sessions(integration_client, db_session) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "reset@example.com", "password": "oldpassword1"},
    )
    old_refresh = reg.json()["refresh_token"]

    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    user = await current_user(db_session, reg.json()["access_token"])
    token = authjwt.mint_password_reset(sub=user.id)

    r = await integration_client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "brandnewpass9"},
    )
    assert r.status_code == 204, r.text

    refreshed = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert refreshed.status_code == 401

    ok = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "brandnewpass9"},
    )
    assert ok.status_code == 200
    bad = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "oldpassword1"},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_reset_token_is_single_use(integration_client, db_session) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "single@example.com", "password": "oldpassword1"},
    )
    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    user = await current_user(db_session, reg.json()["access_token"])
    token = authjwt.mint_password_reset(sub=user.id)

    first = await integration_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "newpass111"}
    )
    assert first.status_code == 204
    second = await integration_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "newpass222"}
    )
    assert second.status_code == 401
