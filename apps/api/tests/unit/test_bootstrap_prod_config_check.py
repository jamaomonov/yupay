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

from typing import Any, cast

import pytest
from starlette.middleware.cors import CORSMiddleware
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


def _cors_kwargs(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build the app for ``settings`` and return the registered CORS middleware options.

    ``create_app`` reads settings via the module-level ``get_settings`` (an
    ``lru_cache``d singleton keyed off env vars), so we swap that binding instead
    of going through env vars — it lets each case construct a ``Settings``
    directly, same as the other tests in this file.
    """
    monkeypatch.setattr("yupay.bootstrap.get_settings", lambda: settings)
    from yupay.bootstrap import create_app

    app = create_app()
    for middleware in app.user_middleware:
        # ``middleware.cls`` is typed as Starlette's ``_MiddlewareFactory`` callback
        # protocol, which mypy won't compare against a concrete class via ``is``
        # without widening to ``object`` first — the check is fine at runtime.
        if cast(object, middleware.cls) is CORSMiddleware:
            return dict(middleware.kwargs)
    raise AssertionError("CORSMiddleware was not registered")


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


@pytest.mark.parametrize("environment", ["dev", "test", "staging"])
def test_cors_wildcard_reflects_any_origin_outside_prod(
    environment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dev tunnels (ngrok/cloudflared) need the wildcard-with-credentials branch."""
    settings = _settings(environment=environment, cors_allow_origins=["*"])
    kwargs = _cors_kwargs(settings, monkeypatch)
    assert kwargs["allow_origin_regex"] == ".*"
    assert kwargs["allow_credentials"] is True


def test_cors_wildcard_is_refused_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CORS_ALLOW_ORIGINS=*`` in prod must never reflect-with-credentials.

    It must fall back to the explicit-origins branch with the literal ``"*"``
    stripped — passing it straight through as ``allow_origins=["*"]`` would
    make Starlette set ``allow_all_origins`` just the same as the regex branch.
    """
    settings = _settings(environment="prod", cors_allow_origins=["*"])
    kwargs = _cors_kwargs(settings, monkeypatch)
    assert "allow_origin_regex" not in kwargs
    assert kwargs["allow_origins"] == []


def test_cors_wildcard_mixed_with_explicit_origins_in_prod_keeps_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(environment="prod", cors_allow_origins=["https://yupay.uz", "*"])
    kwargs = _cors_kwargs(settings, monkeypatch)
    assert kwargs["allow_origins"] == ["https://yupay.uz"]


def test_cors_explicit_origins_in_prod_are_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``"*"`` present ⇒ behaviour is identical to before this guard existed."""
    origins = ["https://yupay.uz", "https://admin.yupay.uz"]
    settings = _settings(environment="prod", cors_allow_origins=origins)
    kwargs = _cors_kwargs(settings, monkeypatch)
    assert kwargs["allow_origins"] == origins
