"""Logging config guards — third-party request loggers must not leak URLs."""

from __future__ import annotations

import logging

from yupay.core.logging import REDACTED_KEYS, _redact_pii, configure_logging


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


def test_redact_pii_masks_chat_id_event() -> None:
    event = _redact_pii(None, "warning", {"event": "telegram.send.rejected", "chat_id": 123456789})
    assert event["chat_id"] == "<redacted>"
