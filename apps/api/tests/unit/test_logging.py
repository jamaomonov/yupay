"""Logging config guards — third-party request loggers must not leak URLs."""

from __future__ import annotations

import json
import logging

from yupay.core.logging import (
    _TRACEBACK_RENDERER,
    REDACTED_KEYS,
    _redact_pii,
    configure_logging,
)


def test_httpx_request_logging_is_muted() -> None:
    """httpx/httpcore log the full request URL at INFO. Waxpeer passes its API
    key as a ``?api=`` query param, so an uncapped httpx logger writes the key
    into stdout/Loki on every call. configure_logging() must cap them at WARNING.
    """
    configure_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


def test_redacted_keys_includes_chat_id() -> None:
    """A Telegram ``chat_id`` is a Telegram user identifier (PII). It must be
    on the blocklist so any future ``log.warning(..., chat_id=...)`` call is
    redacted even if a reviewer misses it."""
    assert "chat_id" in REDACTED_KEYS


def test_redacted_keys_includes_blog_reader_identity() -> None:
    """Anonymous likes/views are a cookie hash, not an IP (ADR-0073)."""
    assert "yp_blog_reader" in REDACTED_KEYS
    assert "reader_hash" in REDACTED_KEYS


def test_redact_pii_masks_chat_id_event() -> None:
    event = _redact_pii(None, "warning", {"event": "telegram.send.rejected", "chat_id": 123456789})
    assert event["chat_id"] == "<redacted>"


def test_redact_pii_masks_user_id_and_pii_aliases() -> None:
    """``user_id`` (the bot logs the Telegram user id under it) and PII-stem
    aliases (``*email``, ``*phone``, ``*_ip``) must be redacted — the redactor
    was exact-key only, so ``customer_email`` / ``client_ip`` slipped through."""
    event = _redact_pii(
        None,
        "info",
        {
            "event": "bot.start",
            "user_id": 111222333,
            "customer_email": "a@b.com",
            "phone_number": "+998901234567",
            "client_ip": "203.0.113.7",
        },
    )
    assert event["user_id"] == "<redacted>"
    assert event["customer_email"] == "<redacted>"
    assert event["phone_number"] == "<redacted>"
    assert event["client_ip"] == "<redacted>"


def test_redact_pii_keeps_safe_keys() -> None:
    """Order IDs, amounts, and language/status codes are OK to log (§9) and must
    NOT be over-redacted by the alias matching."""
    event = _redact_pii(
        None,
        "info",
        {
            "event": "order.paid",
            "order_id": "abc-123",
            "amount": "5000",
            "language_code": "ru",
            "sku_id": "sku-9",
        },
    )
    assert event["order_id"] == "abc-123"
    assert event["amount"] == "5000"
    assert event["language_code"] == "ru"
    assert event["sku_id"] == "sku-9"


def test_prod_tracebacks_carry_no_frame_locals() -> None:
    """structlog 25.x's ``dict_tracebacks`` shorthand renders every frame's
    locals. The worker logs ``listen_failed`` with ``log.exception`` once per
    poll tick for as long as Postgres is unreachable, and the asyncpg connect
    frame's locals hold the DSN — password and all. Prod's JSON renderer must
    therefore render tracebacks with locals off.
    """
    try:
        _connect_and_fail()
    except OSError:
        rendered = _TRACEBACK_RENDERER(None, "error", {"event": "listen_failed", "exc_info": True})

    blob = json.dumps(rendered, default=str)
    assert "s3cret-db-password" not in blob  # the local, not the message
    assert "OSError" in blob  # the exception itself still renders


def _connect_and_fail() -> None:
    """Raise with a credential sitting in the frame's locals, as asyncpg does."""
    dsn = "postgresql://yupay_app:s3cret-db-password@postgres:5432/yupay"  # noqa: F841
    raise OSError("connection refused")
