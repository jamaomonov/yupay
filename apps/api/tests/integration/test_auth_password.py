"""Email/password auth flows: register, login, verify, forgot, reset."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _get_user_by_email(db_session: AsyncSession, email: str) -> User:
    """Resolve a user row by email.

    Registration no longer opens a session (Task 2 of the phase-3 flow), so
    tests can't resolve the just-registered user via ``current_user`` +
    access token anymore — they look the row up directly instead.
    """
    return (await db_session.execute(select(User).where(User.email == email))).scalar_one()


async def _verify_registered_user(
    client: AsyncClient, db_session: AsyncSession, reg: Response
) -> Response:
    """Verify a just-registered account's email via the real endpoint.

    ``login_password`` rejects unverified accounts (see
    ``test_auth_verification_gate.py``), so every test here that registers a
    user and then immediately logs in must drive verification first, the
    same way a real user would after clicking the emailed link. The user id
    is resolved via the email ``RegisterOut`` echoes back rather than via
    ``current_user`` (register no longer returns an access token).

    Returns the ``/auth/verify-email`` response so callers can use the
    session it opens (Task 2: verify-email auto-logs-in).
    """
    from yupay.modules.auth import jwt as authjwt

    email = reg.json()["email"]
    user = await _get_user_by_email(db_session, email)
    token = authjwt.mint_email_verify(sub=user.id)
    r = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    return r


async def test_register_returns_verification_required(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "newbie@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"status": "verification_required", "email": "newbie@example.com"}
    # No session is opened at registration anymore (Task 2): no access
    # token in the body, no refresh cookie set.
    assert "access_token" not in r.json()
    assert "refresh_token" not in r.cookies


async def test_register_then_verify_auto_logs_in(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "newbie2@example.com", "password": "hunter2hunter2"},
    )
    assert reg.status_code == 201, reg.text

    verify = await _verify_registered_user(integration_client, db_session, reg)
    body = verify.json()
    assert body["access_token"]
    assert "refresh_token" not in body
    assert verify.cookies.get("refresh_token")

    me = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "newbie2@example.com"


async def test_register_duplicate_email_conflicts(integration_client: AsyncClient) -> None:
    payload = {"email": "dupe@example.com", "password": "hunter2hunter2"}
    first = await integration_client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await integration_client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_password(
    integration_client: AsyncClient, db_session
) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "loginok@example.com", "password": "hunter2hunter2"},
    )
    await _verify_registered_user(integration_client, db_session, reg)
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "loginok@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    # Login sets the HttpOnly refresh cookie and keeps it out of the body.
    assert "refresh_token" not in body
    set_cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith("refresh_token="))
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


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
    assert reg.status_code == 201, reg.text
    from yupay.modules.auth import jwt as authjwt

    user = await _get_user_by_email(db_session, "verify@example.com")
    token = authjwt.mint_email_verify(sub=user.id)

    r = await integration_client.post("/api/v1/auth/verify-email", json={"token": token})
    # Verify-email now opens a session (Task 2), not a bare 204.
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]

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
    assert reg.status_code == 201, reg.text

    from yupay.modules.auth import jwt as authjwt

    user = await _get_user_by_email(db_session, "reset@example.com")

    # Registration no longer opens a session (Task 2) — verify first to get
    # one, and use its refresh cookie as the "pre-reset" session to prove
    # reset revokes it.
    verify_token = authjwt.mint_email_verify(sub=user.id)
    verify = await integration_client.post(
        "/api/v1/auth/verify-email", json={"token": verify_token}
    )
    assert verify.status_code == 200, verify.text
    old_refresh = verify.cookies["refresh_token"]

    token = authjwt.mint_password_reset(sub=user.id)
    r = await integration_client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "brandnewpass9"},
    )
    assert r.status_code == 204, r.text

    # The pre-reset refresh cookie is now dead (all sessions revoked).
    integration_client.cookies.clear()
    refreshed = await integration_client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh}
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
    assert reg.status_code == 201, reg.text
    from yupay.modules.auth import jwt as authjwt

    user = await _get_user_by_email(db_session, "single@example.com")
    token = authjwt.mint_password_reset(sub=user.id)

    first = await integration_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "newpass111"}
    )
    assert first.status_code == 204
    second = await integration_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "newpass222"}
    )
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_still_runs_password_verify(
    integration_client, monkeypatch
) -> None:
    """Anti-enumeration: an absent account still triggers a verify against the dummy hash.

    Without this, an unknown email would skip argon2 entirely and answer faster than a
    wrong password on a real account — a timing oracle for account existence.
    """
    from yupay.modules.auth import service as auth_service
    from yupay.modules.auth.security import verify_password as real_verify

    seen_hashes: list[str] = []

    async def _counting_verify(plain: str, hashed: str) -> bool:
        seen_hashes.append(hashed)
        return await real_verify(plain, hashed)

    monkeypatch.setattr(auth_service, "verify_password", _counting_verify)

    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-here@example.com", "password": "whatever12"},
    )
    assert r.status_code == 401
    # A verify ran, and it used the module-level constant dummy hash.
    assert seen_hashes == [auth_service._DUMMY_HASH]
