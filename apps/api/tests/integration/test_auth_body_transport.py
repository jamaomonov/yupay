"""The mobile app's token transport (ADR-0101): both tokens in the body, no cookie.

A browser keeps the refresh token in an ``HttpOnly`` cookie. The app has no cookie jar
it controls, so it asks for the token in the body with ``X-Yupay-Token-Transport: body``
and sends it back in the body to refresh and log out. A cookie is never answered with a
body token, or script on the website could read its own session out.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.auth import jwt as authjwt
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio
BODY = {"X-Yupay-Token-Transport": "body"}
CREDS = {"email": "app@example.com", "password": "hunter2hunter2"}


async def _verified_account(client: AsyncClient, db_session: AsyncSession) -> None:
    reg = await client.post("/api/v1/auth/register", json=CREDS)
    assert reg.status_code == 201, reg.text
    user = (await db_session.execute(select(User).where(User.email == CREDS["email"]))).scalar_one()
    verify = await client.post(
        "/api/v1/auth/verify-email", json={"token": authjwt.mint_email_verify(sub=user.id)}
    )
    assert verify.status_code == 200, verify.text
    client.cookies.clear()


async def test_login_in_body_mode_returns_both_tokens_and_sets_no_cookie(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _verified_account(integration_client, db_session)
    r = await integration_client.post("/api/v1/auth/login", json=CREDS, headers=BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_expires_in"] > 0
    assert not any(h.startswith("refresh_token=") for h in r.headers.get_list("set-cookie"))


async def test_a_browser_login_keeps_the_refresh_token_out_of_the_body(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _verified_account(integration_client, db_session)
    r = await integration_client.post("/api/v1/auth/login", json=CREDS)
    assert r.status_code == 200, r.text
    assert "refresh_token" not in r.json()
    assert "refresh_expires_in" not in r.json()


async def test_body_refresh_rotates_and_the_old_token_dies(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _verified_account(integration_client, db_session)
    first = (await integration_client.post("/api/v1/auth/login", json=CREDS, headers=BODY)).json()[
        "refresh_token"
    ]

    r = await integration_client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200, r.text
    second = r.json()["refresh_token"]
    assert second
    assert second != first
    assert not any(h.startswith("refresh_token=") for h in r.headers.get_list("set-cookie"))

    replay = await integration_client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401


async def test_a_cookie_refresh_is_never_answered_in_the_body(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _verified_account(integration_client, db_session)
    login = await integration_client.post("/api/v1/auth/login", json=CREDS)
    cookie = login.cookies["refresh_token"]
    integration_client.cookies.clear()

    r = await integration_client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": cookie}, headers=BODY
    )
    assert r.status_code == 200, r.text
    assert "refresh_token" not in r.json()


async def test_body_logout_revokes_the_refresh_token(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _verified_account(integration_client, db_session)
    token = (await integration_client.post("/api/v1/auth/login", json=CREDS, headers=BODY)).json()[
        "refresh_token"
    ]

    out = await integration_client.post("/api/v1/auth/logout", json={"refresh_token": token})
    assert out.status_code == 204

    r = await integration_client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401


async def test_an_empty_body_falls_back_to_the_cookie(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The mini app logs out with ``{}``; that must still revoke the cookie session."""
    await _verified_account(integration_client, db_session)
    cookie = (await integration_client.post("/api/v1/auth/login", json=CREDS)).cookies[
        "refresh_token"
    ]
    integration_client.cookies.clear()

    out = await integration_client.post(
        "/api/v1/auth/logout", json={}, cookies={"refresh_token": cookie}
    )
    assert out.status_code == 204
    r = await integration_client.post("/api/v1/auth/refresh", cookies={"refresh_token": cookie})
    assert r.status_code == 401
