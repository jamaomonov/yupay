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
