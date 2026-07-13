"""Startup check for a half-configured production environment.

The motivating incident: the stack was deployed with an empty
``TELEGRAM_BOT_TOKEN``, the operator later filled it in but applied it with
``docker compose restart`` — which does not re-read ``env_file`` — so the API
kept running with the empty value. Nothing said so. Mini-app ``initData`` is
HMAC-signed with the bot token, so every ``/auth/telegram/webapp`` call would
401 and users would land on the error screen, while every container reported
"healthy". This check turns that silence into a log line.

It warns rather than raises on purpose: a stack must still be able to come up
before its third-party credentials exist (that is how this one was rolled out),
and refusing to boot would take the storefront down over a disabled integration.
"""

from __future__ import annotations

import pytest
from yupay.bootstrap import missing_prod_settings
from yupay.core.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build Settings with the required fields filled, minus any overrides."""
    base: dict[str, object] = {
        "environment": "prod",
        "telegram_bot_token": "123456:REAL",
        "auth_email_pepper": "pepper",
        "r2_account_id": "acct",
        "r2_access_key_id": "key",
        "r2_secret_access_key": "secret",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_fully_configured_prod_reports_nothing() -> None:
    assert missing_prod_settings(_settings()) == []


def test_empty_bot_token_is_reported() -> None:
    missing = missing_prod_settings(_settings(telegram_bot_token=""))
    assert "TELEGRAM_BOT_TOKEN" in missing


def test_empty_r2_credentials_are_reported() -> None:
    missing = missing_prod_settings(_settings(r2_account_id="", r2_access_key_id=""))
    assert "R2_ACCOUNT_ID" in missing
    assert "R2_ACCESS_KEY_ID" in missing


def test_empty_email_pepper_is_reported() -> None:
    assert "AUTH_EMAIL_PEPPER" in missing_prod_settings(_settings(auth_email_pepper=""))


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_non_prod_is_never_reported(environment: str) -> None:
    """Local work routinely runs without third-party credentials — stay quiet."""
    settings = _settings(
        environment=environment,
        telegram_bot_token="",
        auth_email_pepper="",
        r2_account_id="",
        r2_access_key_id="",
        r2_secret_access_key="",
    )
    assert missing_prod_settings(settings) == []
