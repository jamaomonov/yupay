"""``users.signup_source``: the surface an account was opened from (migration 0103)."""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.users.models import TelegramLink, User

from tests.integration.test_auth_routes import _login_via_webapp, _sign_widget

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fixed_now() -> int:
    """A real ``auth_date``: Telegram payloads are checked for age, not frozen time."""
    return int(time.time())


async def _by_email(db: AsyncSession, email: str) -> User:
    return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def _by_telegram(db: AsyncSession, tg_id: int) -> User:
    link = (
        await db.execute(select(TelegramLink).where(TelegramLink.tg_user_id == tg_id))
    ).scalar_one()
    return (await db.execute(select(User).where(User.id == link.user_id))).scalar_one()


@pytest.mark.parametrize(("header", "expected"), [("mobile", "mobile"), ("web", "web")])
async def test_registration_records_the_declared_surface(
    integration_client: AsyncClient, db_session: AsyncSession, header: str, expected: str
) -> None:
    email = f"{header}@example.com"
    r = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2hunter2"},
        headers={"X-Yupay-Surface": header},
    )
    assert r.status_code == 201, r.text
    assert (await _by_email(db_session, email)).signup_source == expected


async def test_an_undeclared_or_unknown_surface_records_unknown(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    r = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "odd@example.com", "password": "hunter2hunter2"},
        headers={"X-Yupay-Surface": "merchant_api"},
    )
    assert r.status_code == 201, r.text
    assert (await _by_email(db_session, "odd@example.com")).signup_source == "unknown"


async def test_the_mini_app_route_always_records_miniapp(
    integration_client: AsyncClient, db_session: AsyncSession, fixed_now: int
) -> None:
    await _login_via_webapp(integration_client, fixed_now)
    user = (await db_session.execute(select(User))).scalars().one()
    assert user.signup_source == "miniapp"


async def test_a_later_sign_in_elsewhere_keeps_the_first_surface(
    integration_client: AsyncClient, db_session: AsyncSession, fixed_now: int
) -> None:
    def widget() -> dict[str, object]:
        p = _sign_widget({"id": "77", "first_name": "A", "auth_date": str(fixed_now)})
        return {"id": 77, "first_name": "A", "auth_date": fixed_now, "hash": p["hash"]}

    first = await integration_client.post(
        "/api/v1/auth/telegram/widget", json=widget(), headers={"X-Yupay-Surface": "mobile"}
    )
    assert first.status_code == 200, first.text
    assert (await _by_telegram(db_session, 77)).signup_source == "mobile"

    # A replayed widget hash is refused, so the second sign-in is a fresh payload.
    p = _sign_widget({"id": "77", "first_name": "B", "auth_date": str(fixed_now)})
    again = await integration_client.post(
        "/api/v1/auth/telegram/widget",
        json={"id": 77, "first_name": "B", "auth_date": fixed_now, "hash": p["hash"]},
        headers={"X-Yupay-Surface": "web"},
    )
    assert again.status_code == 200, again.text
    db_session.expire_all()
    assert (await _by_telegram(db_session, 77)).signup_source == "mobile"
