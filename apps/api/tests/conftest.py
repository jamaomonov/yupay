"""Pytest fixtures shared across the api test suite."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> Iterator[None]:
    """Populate env vars needed by ``Settings`` before anything imports the config.

    A session-scoped autouse fixture that runs before every test gets a fresh
    ``get_settings`` cache. JWT keys are generated once and reused across the suite.
    """
    sk = Ed25519PrivateKey.generate()
    private_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        sk.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    env = {
        "ENVIRONMENT": "test",
        "JWT_PRIVATE_KEY": private_pem,
        "JWT_PUBLIC_KEY": public_pem,
        "JWT_KID": "test",
        "AUTH_EMAIL_PEPPER": "test-pepper",
        "TELEGRAM_BOT_TOKEN": "123456:TEST",
        # Ops alerting stays off for the whole suite. `send_admin_alert`
        # short-circuits on an empty token, so nothing reaches
        # api.telegram.org — without this a developer's real .env turns every
        # error-path test into an outbound HTTP call, and the suite crawls.
        "TG_ALERT_BOT_TOKEN": "",
        "TG_ALERT_CHAT_ID": "",
    }
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    # Reset the cached Settings so subsequent imports pick the test values up.
    from yupay.core import config as cfg

    cfg.get_settings.cache_clear()

    try:
        yield
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg.get_settings.cache_clear()


@pytest.fixture
async def app() -> Any:
    """Build a fresh FastAPI app for each test."""
    from yupay.bootstrap import create_app

    return create_app()


@pytest.fixture
async def client(app: object) -> AsyncIterator[AsyncClient]:
    """An ``httpx.AsyncClient`` bound to the app via ASGI transport."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
