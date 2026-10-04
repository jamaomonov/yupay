"""Merchant-cabinet sign-up and admin login, shared by the cabinet and P2P tests.

The fixtures here are registered as a plugin by ``tests/conftest.py`` (``cabinet_mails``,
``admin_headers``) so a test asks for them by parameter name instead of
importing them — an imported fixture shadowed by a parameter is ruff F811.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import Settings, get_settings
from yupay.modules.merchants import cabinet_auth_routes, cabinet_notify
from yupay.modules.users.models import TelegramLink, User

BASE = "/merchant/cabinet"
CABINET_URL = "https://reseller.yupay.test"
PASSWORD = "correct-horse-battery"
BOT_TOKEN = "123456:TEST"


def sign_init_data(fields: dict[str, str]) -> str:
    """Telegram WebApp ``initData`` signed with the test bot token."""
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def login_admin(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    """Log a Telegram user in, grant it the admin role, return its auth header.

    Crediting a deposit is support's job, not a merchant's, so the one thing
    the cabinet tests cannot do through the cabinet is give themselves money —
    which is the point of the whole onboarding shape.
    """
    user_json = json.dumps({"id": 92, "first_name": "Admin"}, separators=(",", ":"))
    init_data = sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 92)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


def capture_cabinet_mail(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Route cabinet e-mail into a list and point links at the test cabinet URL."""
    mails: list[dict[str, str]] = []

    async def _send(*, to: str, subject: str, html: str, text: str) -> str:
        mails.append({"to": to, "html": html, "subject": subject, "text": text})
        return "msg-test"

    base = get_settings().model_dump()
    base["merchant_cabinet_url"] = CABINET_URL
    monkeypatch.setattr(cabinet_auth_routes, "send_email", _send)
    monkeypatch.setattr(cabinet_auth_routes, "get_settings", lambda: Settings(**base))
    # The security notices import ``send_email`` into their own module, so
    # they need their own patch — without it they fall through to a real
    # (unconfigured) send, which is swallowed, and a test asserting on them
    # would silently assert on nothing.
    monkeypatch.setattr(cabinet_notify, "send_email", _send)
    return mails


def auth(token: str) -> dict[str, str]:
    """A bearer header."""
    return {"Authorization": f"Bearer {token}"}


async def signed_up(
    client: AsyncClient, mails: list[dict[str, str]], email: str
) -> tuple[str, str]:
    """Register and confirm. Returns ``(access_token, merchant_id)``."""
    r = await client.post(
        f"{BASE}/register",
        json={"email": email, "password": PASSWORD, "title": "ACME", "accept_offer": True},
    )
    assert r.status_code == 201, r.text
    link = re.search(r'href="([^"]+/confirm\?token=[^"]+)"', mails[-1]["html"])
    assert link is not None
    token = parse_qs(urlparse(link.group(1)).query)["token"][0]
    tokens = await client.post(f"{BASE}/confirm", json={"token": token})
    assert tokens.status_code == 200, tokens.text
    access = str(tokens.json()["access_token"])
    me = await client.get(f"{BASE}/me", headers=auth(access))
    return access, str(me.json()["merchant_id"])


@pytest.fixture(name="admin_headers")
async def admin_headers_fixture(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """An admin's auth header (see :func:`login_admin`)."""
    return await login_admin(integration_client, db_session)


@pytest.fixture(name="cabinet_mails")
def cabinet_mails_fixture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Cabinet e-mails sent during the test (see :func:`capture_cabinet_mail`)."""
    return capture_cabinet_mail(monkeypatch)
