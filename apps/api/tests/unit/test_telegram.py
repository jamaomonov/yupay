"""Unit tests for Telegram signature verification.

We re-implement the Telegram algorithm here to **generate** valid payloads and feed them
back through :mod:`yupay.modules.auth.telegram`. That way the test fails if either the
canonical algorithm or the verifier drifts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from yupay.core import clock
from yupay.modules.auth import telegram as tg

BOT_TOKEN = "123456:TEST"
MAX_AGE = 86_400  # 24h


def _data_check_string(fields: dict[str, str]) -> bytes:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    return "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    digest = hmac.new(secret_key, _data_check_string(fields), hashlib.sha256).hexdigest()
    fields = {**fields, "hash": digest}
    return urlencode(fields)


def _sign_widget(fields: dict[str, str], token: str = BOT_TOKEN) -> dict[str, str]:
    secret_key = hashlib.sha256(token.encode("utf-8")).digest()
    digest = hmac.new(secret_key, _data_check_string(fields), hashlib.sha256).hexdigest()
    return {**fields, "hash": digest}


@pytest.fixture(autouse=True)
def _frozen_clock():
    """Freeze the clock so ``auth_date`` deltas are deterministic."""
    fixed = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
    clock.set_clock(lambda: fixed)
    yield int(fixed.timestamp())
    clock.reset_clock()


def _valid_init_data(auth_date: int, *, tg_id: int = 7) -> str:
    user_json = json.dumps(
        {"id": tg_id, "first_name": "Yu", "username": "yu_test", "language_code": "ru"},
        separators=(",", ":"),
    )
    return _sign_init_data({"user": user_json, "auth_date": str(auth_date), "query_id": "q1"})


def test_verify_init_data_happy_path(_frozen_clock) -> None:
    payload = _valid_init_data(_frozen_clock)
    result = tg.verify_init_data(payload, bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)
    assert result.user.id == 7
    assert result.user.first_name == "Yu"
    assert result.query_id == "q1"


def test_verify_init_data_rejects_tampered_hash(_frozen_clock) -> None:
    payload = _valid_init_data(_frozen_clock)
    # Flip the last hex char of the hash.
    tampered = payload[:-1] + ("0" if payload[-1] != "0" else "1")
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_init_data(tampered, bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)


def test_verify_init_data_rejects_wrong_bot_token(_frozen_clock) -> None:
    payload = _valid_init_data(_frozen_clock)
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_init_data(payload, bot_token="999:OTHER", max_age_seconds=MAX_AGE)


def test_verify_init_data_rejects_stale_payload(_frozen_clock) -> None:
    old_auth_date = _frozen_clock - (MAX_AGE + 10)
    payload = _valid_init_data(old_auth_date)
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_init_data(payload, bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)


def test_verify_init_data_rejects_future_payload(_frozen_clock) -> None:
    payload = _valid_init_data(_frozen_clock + 3600)  # 1h in the future, beyond skew
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_init_data(payload, bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)


def test_verify_init_data_rejects_empty() -> None:
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_init_data("", bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)


def test_verify_login_widget_happy_path(_frozen_clock) -> None:
    payload = _sign_widget(
        {
            "id": "42",
            "first_name": "Yu",
            "username": "yu_test",
            "auth_date": str(_frozen_clock),
        }
    )
    result = tg.verify_login_widget(dict(payload), bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)
    assert result.user.id == 42
    assert result.user.first_name == "Yu"


def test_verify_login_widget_rejects_bad_hash(_frozen_clock) -> None:
    payload = _sign_widget({"id": "1", "first_name": "X", "auth_date": str(_frozen_clock)})
    payload["hash"] = "0" * 64
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_login_widget(dict(payload), bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)


def test_verify_login_widget_rejects_stale(_frozen_clock) -> None:
    payload = _sign_widget(
        {"id": "1", "first_name": "X", "auth_date": str(_frozen_clock - MAX_AGE - 1)}
    )
    with pytest.raises(tg.TelegramAuthError):
        tg.verify_login_widget(dict(payload), bot_token=BOT_TOKEN, max_age_seconds=MAX_AGE)
