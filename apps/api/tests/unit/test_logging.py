"""Logging config guards — third-party request loggers must not leak URLs."""

from __future__ import annotations

import logging

from yupay.core.logging import configure_logging


def test_httpx_request_logging_is_muted() -> None:
    """httpx/httpcore log the full request URL at INFO. Waxpeer passes its API
    key as a ``?api=`` query param, so an uncapped httpx logger writes the key
    into stdout/Loki on every call. configure_logging() must cap them at WARNING.
    """
    configure_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name
