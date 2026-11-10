"""The admin panel's own session kind (audit 2026-11-10).

Before, any session of an account carrying the ``admin`` role — the mini app's,
the storefront's — could call ``/admin/*``. Now only a session opened through
the admin login (``auth_sessions.kind='admin'``, tokens carrying ``adm``) can,
and it rotates through its own host-only cookie on ``/auth/admin/refresh``.

The suite at large runs with ``ADMIN_SESSION_REQUIRED=false`` (its fixtures
grant the role to an ordinary session); these tests turn the rule on.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.auth.models import AuthSession
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"  # the conftest-managed TELEGRAM_BOT_TOKEN
ADMIN_PROBE = "/api/v1/admin/merchants"


@pytest.fixture(autouse=True)
def _admin_session_required(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ADMIN_SESSION_REQUIRED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _widget(tg_id: int, auth_date: int) -> dict[str, object]:
    fields = {"id": str(tg_id), "first_name": "Boss", "auth_date": str(auth_date)}
    data = "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode()
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    return {
        "id": tg_id,
        "first_name": "Boss",
        "auth_date": auth_date,
        "hash": hmac.new(secret, data, hashlib.sha256).hexdigest(),
    }


async def _admin_with_storefront_session(
    client: AsyncClient, db: AsyncSession, tg_id: int
) -> tuple[str, int]:
    """An admin account, signed in on the storefront. Returns its storefront token."""
    now = int(time.time())
    reg = await client.post("/api/v1/auth/telegram/widget", json=_widget(tg_id, now))
    assert reg.status_code == 200, reg.text
    token = str(reg.json()["access_token"])
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    await db.execute(update(User).where(User.id == me.json()["id"]).values(roles=["admin"]))
    await db.commit()
    return token, now


async def test_a_storefront_session_of_an_admin_cannot_use_the_admin_api(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _ = await _admin_with_storefront_session(integration_client, db_session, 9101)
    r = await integration_client.get(ADMIN_PROBE, headers={"Authorization": f"Bearer {token}"})
    # 401, not 403: the SPA sends the operator to its login, not to «no rights».
    assert r.status_code == 401, r.text


async def test_the_admin_login_opens_an_admin_session_that_works(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, now = await _admin_with_storefront_session(integration_client, db_session, 9102)
    login = await integration_client.post(
        "/api/v1/auth/telegram/widget/admin", json=_widget(9102, now + 5)
    )
    assert login.status_code == 200, login.text
    # Its own cookie, host-only, on the admin auth routes only — never the
    # storefront's `.yupay.uz`-wide one.
    set_cookie = login.headers["set-cookie"]
    assert set_cookie.startswith("admin_refresh_token=")
    assert "Path=/api/v1/auth/admin" in set_cookie
    assert "Domain=" not in set_cookie
    assert "refresh_token=" not in set_cookie.split("admin_refresh_token=", 1)[0]

    token = login.json()["access_token"]
    r = await integration_client.get(ADMIN_PROBE, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    kinds = (await db_session.execute(select(AuthSession.kind))).scalars().all()
    assert "admin" in kinds


async def test_the_admin_cookie_rotates_on_its_own_route_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, now = await _admin_with_storefront_session(integration_client, db_session, 9103)
    login = await integration_client.post(
        "/api/v1/auth/telegram/widget/admin", json=_widget(9103, now + 5)
    )
    admin_refresh = login.cookies["admin_refresh_token"]

    # The storefront's refresh will not turn it into a session of either kind.
    as_storefront = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": admin_refresh}
    )
    assert as_storefront.status_code == 401

    rotated = await integration_client.post(
        "/api/v1/auth/admin/refresh", cookies={"admin_refresh_token": admin_refresh}
    )
    assert rotated.status_code == 200, rotated.text
    token = rotated.json()["access_token"]
    r = await integration_client.get(ADMIN_PROBE, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


async def test_a_storefront_refresh_token_cannot_become_an_admin_session(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _admin_with_storefront_session(integration_client, db_session, 9104)
    storefront_refresh = integration_client.cookies.get("refresh_token")
    assert storefront_refresh
    r = await integration_client.post(
        "/api/v1/auth/admin/refresh", cookies={"admin_refresh_token": storefront_refresh}
    )
    assert r.status_code == 401


async def test_admin_refresh_ends_the_session_once_the_role_is_gone(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, now = await _admin_with_storefront_session(integration_client, db_session, 9105)
    login = await integration_client.post(
        "/api/v1/auth/telegram/widget/admin", json=_widget(9105, now + 5)
    )
    admin_refresh = login.cookies["admin_refresh_token"]
    await db_session.execute(update(User).values(roles=[]))
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/auth/admin/refresh", cookies={"admin_refresh_token": admin_refresh}
    )
    assert r.status_code == 401
    live = (
        (
            await db_session.execute(
                select(AuthSession).where(
                    AuthSession.kind == "admin", AuthSession.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert live == []


async def test_production_refuses_the_admin_cookie_from_another_origin(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every `*.yupay.uz` host is same-site, so the cookie alone is not enough."""
    from yupay.modules.auth import routes

    prod = cfg.get_settings().model_copy(update={"environment": "prod"})
    monkeypatch.setattr(routes, "get_settings", lambda: prod)
    r = await integration_client.post(
        "/api/v1/auth/admin/refresh",
        cookies={"admin_refresh_token": "anything"},
        headers={"Origin": "https://yupay.uz"},
    )
    assert r.status_code == 401
    assert "admin panel" in r.text
